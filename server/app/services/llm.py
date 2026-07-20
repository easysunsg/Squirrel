"""LLM service for intelligent parsing and generation."""

import json
import os
from typing import Optional
import litellm
import logging

from app.core.config import settings
from app.models.schemas import RecipeRecommendResult

logger = logging.getLogger(__name__)

RECIPE_RECOMMEND_PROMPT = """
## 角色定位
你是专注零浪费的家庭食材菜谱规划助手，核心使命是帮用户用掉即将过期的食材，减少食物浪费。请根据用户提供的临期食材清单，生成实用、家常、易操作的菜谱方案。
严格按照指定JSON格式输出结果，禁止输出任何解释、markdown、代码块等额外内容，只输出纯JSON字符串。

## 输入信息
1. 临期食材清单：{expiring_food_list}
   （格式为数组，每项包含：name=食材名称, quantity=剩余数量, unit=单位, expire_days=剩余保质期天数）
2. 用户饮食偏好/忌口：{user_preference}（无则为"无特殊要求"）
3. 用户的每日提醒时间：{reminder_time}（一天中最方便处理食材的时段，据此推荐适合该时段的菜品，如提醒时间为18:00则推荐晚餐食谱）

## 输出Schema（严格遵守，字段不可新增/删减/修改类型）
```json
{{
  "title": "字符串，必填，活动主题标题，例如「今日临期食材灵感菜谱」",
  "subtitle": "字符串，必填，副标题slogan，贴合零浪费主题，例如「巧用临期食材，践行零剩食生活」",
  "intro": "字符串，必填，开头引导语，亲切自然，点明用到的核心临期食材，100字以内",
  "recipe_list": "数组，必填，推荐3-4道家常菜，每道菜结构如下：",
  [
    {{
      "recipe_name": "字符串，必填，菜谱名称，家常易懂",
      "core_expiring_food": "数组，必填，这道菜用到的临期食材名称列表",
      "other_ingredients": "数组，必填，其他需要的常见家常食材，尽量简单易得",
      "cooking_steps": "数组，必填，烹饪步骤，3-6步，清晰易懂，每步一句话",
      "estimated_time": "字符串，必填，预计耗时，例如「15分钟」",
      "difficulty": "字符串，必填，难度等级：简单/中等/偏难，优先推荐简单级",
      "waste_tip": "字符串，必填，零浪费小贴士，说明这道菜如何消耗临期食材、或食材边角料利用技巧"
    }}
  ],
  "summary_tip": "字符串，必填，结尾总结建议，包含临期食材保存技巧、剩余食材处理建议，100字以内"
}}

## 核心推荐原则（必须严格遵守）
1. 临期优先，最大化消耗：每道菜必须至少用到 1 种临期食材，优先选择能大量消耗临期食材的菜谱。
2. 家常易做，门槛极低：只推荐普通家庭日常能做的菜品，不需要专业工具、稀有食材，优先选 15-30 分钟能完成的简单菜。
3. 食材通用，减少额外采购：其他辅料尽量用盐、油、酱油、葱姜蒜等家家都有的调料。
4. 用量合理，符合家庭场景：每道菜中用到的临期食材用量不得超过用户当前的剩余库存，按3人左右的家庭份推荐。
5. 品类多样，搭配合理：菜品类型尽量不重复，兼顾主食、菜肴、饮品等不同类型。

## 详细规则
- 若临期食材只有 1-2 种且数量极少时，推荐小分量配菜或辅食，不要硬推主菜。
- 临期食材种类较多（>=8种）时，优先推荐能同时用到多种食材的菜谱（如大乱炖、杂蔬炒饭），最大化一次消耗。
- 若临期食材是调料或辅料（如酱油、盐），只能作为配菜出现，不得作为核心食材推荐。
- 绝对避开用户的忌口食材，符合饮食偏好；若临期食材本身就是过敏原，提示「该食材为您的忌口食材，建议尽快处理，不推荐食用」。
- 烹饪步骤要具体可落地，不要模糊表述。
- 零浪费小贴士要实用，比如"牛奶快过期可以做布丁、蒸蛋羹"等。
- 语气亲切温暖，有生活感，像贴心的居家小管家。

## 最终禁令
- 绝对禁止推荐需要稀有食材、专业工具的复杂菜品。
- 绝对禁止脱离给定的临期食材凭空推荐菜谱，每道菜必须用到清单里的食材。
- 绝对禁止输出 JSON 以外的任何内容。
- 绝对不推荐不安全的食用方式，过期变质的食材绝对不能建议食用。
- 若某食材已是用户过敏原/忌口，该食材不能出现在任何菜谱的core_expiring_food或other_ingredients中。
"""

# Common allergen keywords to intercept in recipe results (simplified Chinese)
ALLERGEN_INTERCEPT_KEYWORDS = [
    "海鲜", "虾", "蟹", "贝", "鱼",
    "花生", "坚果", "杏仁", "腰果",
    "牛奶", "乳糖", "奶油", "芝士", "奶酪", "黄油",
    "鸡蛋", "蛋",
    "大豆", "豆腐",
    "小麦", "面筋", "面粉",
    "辛辣", "辣椒", "花椒",
    "猪肉", "牛肉", "羊肉", "鸡肉",
    "素食", "蔬菜",
]

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

# litellm provider prefix mapping
PROVIDER_PREFIX_MAP: dict[str, str] = {
    "openai": "openai/",
    "anthropic": "anthropic/",
    "ollama": "ollama/",
    "google": "gemini/",
    "deepseek": "deepseek/",
    "reality": "openai/",
}


class LLMService:
    """Wrapper for LLM API calls with fallback to rule-based parsing."""

    def __init__(self):
        self.provider = settings.ai_provider
        self.api_key = settings.ai_api_key
        self.base_url = settings.ai_base_url
        self.model = settings.ai_model
        # 配置化超时
        self.timeout = getattr(settings, "ai_timeout", 30.0)
        self.max_retries = getattr(settings, "ai_max_retries", 2)
        self.enabled = self.provider != "mock" and bool(self.api_key)
        self._provider_prefix = PROVIDER_PREFIX_MAP.get(self.provider, "openai/")

        if self.enabled:
            logger.info(
                "LLM service initialized provider=%s model=%s base_url=%s",
                self.provider,
                self.model,
                self.base_url,
            )
        else:
            logger.info("LLM service disabled, using rule-based fallback")

    def _call_model(self, messages: list[dict], response_format: Optional[dict] = None) -> str:
        model_str = f"{self._provider_prefix}{self.model}"
        try:
            response = litellm.completion(
                model=model_str,
                messages=messages,
                temperature=0.1,
                drop_params=True,
                response_format=response_format,
                api_key=self.api_key or None,
                base_url=self.base_url or None,
                timeout=self.timeout,
                num_retries=self.max_retries,
            )
            if not response.choices:
                raise RuntimeError("LLM 返回空 choices 列表")
            content = response.choices[0].message.content or ""
            return content.strip()
        except Exception:
            logger.exception("LLM API call failed")
            raise

    def extract_raw_json(self, messages: list[dict], response_format: Optional[dict] = None) -> str:
        """Low-level: send messages and get raw text back. Used by parser.py."""
        if not self.enabled:
            raise RuntimeError("LLM service is not enabled")
        return self._call_model(messages, response_format)

    def classify_intent(
        self,
        text: str,
        inventory_summary: str = "",
        current_context: dict | None = None,
    ) -> dict:
        """Classify user intent with LLM.

        Args:
            text: User input text.
            inventory_summary: Comma-separated item titles for context.
            current_context: Current context item from multi-turn conversation
                             (e.g. {"title": "全麦面包", "location": "厨房"}).

        Returns:
            {
                "intent": str,  # add/consume/remove/update_location/update_expiry/expiry_query/location_query/search_query/idle_query/recipe/chat
                "entities": {
                    "target": str | None,
                    "count": int | None,
                    "unit": str | None,
                    "location": str | None,
                    "remaining_pct": int | None,
                    "expire_days": int | None,
                }
            }
        """
        if not self.enabled:
            return {"intent": "unknown", "entities": {}}

        system_prompt = """你是一个家庭库存管理助手，负责理解用户的自然语言指令并提取关键信息。

用户可能的意图类型：
- add: 添加新物品到库存（例如：买了、购入、新增、存入）
- consume: 消耗物品（例如：用了、吃了一半、喝了）
- remove: 移除物品（例如：扔掉、坏了、清掉）
- update_location: 更新物品位置（例如：换到、移到、放到）
- update_expiry: 更新保质期（例如：保质期延长、明天过期）
- expiry_query: 查询临期物品（例如：什么快过期、临期物品）
- location_query: 查询物品位置（例如：螺蛳粉在哪、放哪了）
- quantity_query: 查询物品数量（例如：还有几个玉米、还剩多少牛奶）
- search_query: 搜索物品（例如：还有什么蔬菜、有什么感冒药）
- idle_query: 查询闲置物品（例如：什么放了很久、长期闲置）
- recipe: 生成菜谱（例如：吃什么、做什么菜、菜谱建议）
- chat: 通用对话（其他情况）

请分析用户输入，返回 JSON 格式：
{
  "intent": "意图类型",
  "entities": {
    "target": "目标物品名称（如果有）",
    "count": 数量（数字，如果有）,
    "unit": "单位（如果有）",
    "location": "位置（如果有）",
    "remaining_pct": 剩余百分比（0-100，如果有）,
    "expire_days": 保质期天数（如果有）
  }
}"""

        # 构建上下文信息（含跨轮代词消解）
        context_parts = []
        if inventory_summary:
            context_parts.append(f"当前库存摘要：{inventory_summary}")
        if current_context and current_context.get("title"):
            ctx_title = current_context["title"]
            ctx_loc = current_context.get("location", "")
            ctx_space = current_context.get("spaceName", "")
            ctx_info = f"上一轮提到的物品：{ctx_title}"
            if ctx_space:
                ctx_info += f"（位于{ctx_space}/{ctx_loc}）"
            elif ctx_loc:
                ctx_info += f"（位于{ctx_loc}）"
            context_parts.append(ctx_info)
            context_parts.append("注意：如果用户使用了「这个」「那个」「它」「这东西」「这」等代词，target 应填上上文物品的名称「{ctx_title}」")

        context_str = "\n".join(context_parts) if context_parts else "无"

        user_prompt = f"""用户输入：{text}

{context_str}

请分析意图并提取实体。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_model(
                messages,
                response_format={"type": "json_object"},
            )
            result = json.loads(response)
            logger.info("Intent classified text=%r intent=%s entities=%s", text, result.get("intent"), result.get("entities"))
            return result
        except Exception:
            logger.exception("Intent classification failed, using fallback")
            return {"intent": "unknown", "entities": {}}

    def generate_recipe(self, ingredients: list[str], urgent_item: str | None = None) -> dict:
        """Generate recipe suggestion based on available ingredients.

        Returns:
            {
                "title": str,
                "description": str,
                "ingredients": str,
                "steps": list[str],
            }
        """
        if not self.enabled:
            return {
                "title": "食材整理建议",
                "description": "当前 LLM 服务未启用，无法生成个性化菜谱。",
                "ingredients": "现有食材",
                "steps": ["检查食材状态", "按需烹调"],
            }

        system_prompt = """你是一个专业的家庭厨师助手，擅长根据现有食材快速生成实用菜谱。

要求：
1. 菜谱必须简单易做，适合家庭日常烹饪
2. 优先使用临期食材，减少浪费
3. 步骤清晰具体，包含时间和火候
4. 返回 JSON 格式：
{
  "title": "菜名",
  "description": "简短描述（1-2句话）",
  "ingredients": "食材清单",
  "steps": ["步骤1", "步骤2", "步骤3"]
}"""

        ingredients_text = "、".join(ingredients) if ingredients else "无明确食材"
        urgent_text = f"\n\n⚠️ 优先使用：{urgent_item}（临期或剩余较多）" if urgent_item else ""

        user_prompt = f"""可用食材：{ingredients_text}{urgent_text}

请生成一个简单实用的菜谱建议。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_model(
                messages,
                response_format={"type": "json_object"},
            )
            result = json.loads(response)
            logger.info("Recipe generated title=%s ingredients_count=%d", result.get("title"), len(ingredients))
            return result
        except Exception:
            logger.exception("Recipe generation failed, using fallback")
            return {
                "title": f"{urgent_item or '食材'}快手消耗餐" if urgent_item else "食材整理建议",
                "description": f"优先消耗 {urgent_item}，减少临期浪费。" if urgent_item else "根据现有食材灵活烹调。",
                "ingredients": f"{urgent_item} 适量，常备调味料" if urgent_item else "现有食材适量",
                "steps": ["确认食材没有变质", "清洗并简单处理", "中火快速烹调或搭配主食食用"],
            }

    def chat_reply(self, user_message: str, context: str = "") -> str:
        """Generate conversational reply.

        Args:
            user_message: User's message
            context: Additional context (inventory summary, etc.)

        Returns:
            Assistant's reply text
        """
        if not self.enabled:
            return "我是库存管理助手。你可以让我录入、查位置、列临期或生成菜谱。"

        system_prompt = """你是一个友好的家庭库存管理助手，名字叫 Squirrel（松鼠）。

你的能力：
- 添加和管理家庭物品库存
- 查询物品位置和状态
- 提醒临期物品
- 根据食材生成菜谱建议
- 回答关于库存管理的问题

回复要求：
- 简洁友好，1-2句话
- 口语化表达
- 遇到不明确的请求时，引导用户提供更多信息"""

        user_prompt = f"""用户：{user_message}

上下文：{context or "无"}

请生成友好的回复。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_model(messages)
            logger.info("Chat reply generated for message=%r", user_message)
            return response
        except Exception:
            logger.exception("Chat reply generation failed, using fallback")
            return "我理解你的意思了。你可以让我录入物品、查位置、列临期或生成菜谱。"


    def generate_expiring_recipe(self, expiring_food_list: list[dict], user_preference: str = "无特殊要求", reminder_time: str = "") -> dict:
        """Generate structured recipe recommendations from expiring ingredients.

        Returns:
            {
                "recipe_recommend": {...} | None,
                "isFallback": bool,
                "fallbackText": str | None,
            }
        """
        if not self.enabled:
            return self._fallback_level2(expiring_food_list)

        # Build allergen interception list from user preferences
        user_allergens = self._extract_allergens(user_preference)

        prompt = RECIPE_RECOMMEND_PROMPT.format(
            expiring_food_list=json.dumps(expiring_food_list, ensure_ascii=False),
            user_preference=user_preference,
            reminder_time=reminder_time or "未设置",
        )

        messages = [
            {"role": "system", "content": "你是零浪费菜谱规划助手。只输出纯 JSON，不输出任何其他内容。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = self._call_model(
                messages,
                response_format={"type": "json_object"},
            )
            raw = json.loads(response)

            # Validate with Pydantic
            validated = RecipeRecommendResult.model_validate(raw)
            result = validated.model_dump()

            # === Allergen interception on result ===
            intercepted = self._intercept_allergens(result, user_allergens)
            if intercepted:
                logger.warning("Recipe result intercepted due to allergen match user_allergens=%s", user_allergens)
                return self._fallback_level1(expiring_food_list, result)

            logger.info(
                "Expiring recipe generated successfully title=%s recipes=%d",
                result.get("title"),
                len(result.get("recipe_list", [])),
            )
            return {"recipe_recommend": result, "isFallback": False, "fallbackText": None}

        except Exception:
            logger.exception("Expiring recipe generation failed, falling back to level-1 template")
            return self._fallback_level1(expiring_food_list, None)

    # ---- internal helpers ----

    def _extract_allergens(self, preference: str) -> list[str]:
        """Extract allergen keywords from user preference string."""
        found = []
        pref_lower = preference.lower()
        for kw in ALLERGEN_INTERCEPT_KEYWORDS:
            if kw in pref_lower:
                found.append(kw)
        # Also check dietaryHabits patterns like "海鲜过敏 🦐" -> "海鲜"
        import re
        habit_allergens = re.findall(r"(.+?)过敏", preference)
        return list(set(found + [a.strip() for a in habit_allergens if a.strip()]))

    def _intercept_allergens(self, recipe: dict, allergens: list[str]) -> bool:
        """Check if any recipe contains allergens. Returns True if intercepted."""
        if not allergens:
            return False
        for card in recipe.get("recipe_list", []):
            all_ingredients = card.get("core_expiring_food", []) + card.get("other_ingredients", [])
            for ing in all_ingredients:
                for a in allergens:
                    if a in ing:
                        logger.warning("Allergen '%s' found in recipe ingredient '%s'", a, ing)
                        return True
        return False

    def _fallback_level1(self, expiring_food_list: list[dict], partial_result: dict | None) -> dict:
        """Level-1 fallback: template-based recipe using expiring ingredients."""
        names = [item.get("name", "") for item in expiring_food_list if item.get("name")]
        name_str = "、".join(names) if names else "临期食材"

        if partial_result:
            # Try to salvage what we can
            fallback = partial_result.copy()
            fallback.setdefault("title", "今日临期食材灵感菜谱")
            fallback.setdefault("subtitle", "巧用临期食材，践行零剩食生活")
            fallback.setdefault("intro", f"本松发现您有 {name_str} 快到期了，这里有几个简单的家常做法～")
            if not fallback.get("recipe_list"):
                fallback["recipe_list"] = self._template_recipes(names)
            fallback.setdefault("summary_tip", "临期食材尽快食用，吃不完可以冷冻保存哦！")
            return {"recipe_recommend": fallback, "isFallback": True, "fallbackText": None}

        return {
            "recipe_recommend": {
                "title": "今日临期食材灵感菜谱",
                "subtitle": "巧用临期食材，践行零剩食生活",
                "intro": f"本松发现您有 {name_str} 快到期了，这里有几个简单的家常做法，一起来看看吧～",
                "recipe_list": self._template_recipes(names),
                "summary_tip": "临期食材尽快食用，吃不完可以冷冻保存。蔬菜类可以焯水后冷冻，牛奶可以做布丁或蒸蛋羹延长食用期。",
            },
            "isFallback": True,
            "fallbackText": None,
        }

    def _template_recipes(self, ingredients: list[str]) -> list[dict]:
        """Generate fallback template recipes from ingredient names."""
        if not ingredients:
            return [
                {
                    "recipe_name": "家常炒时蔬",
                    "core_expiring_food": [],
                    "other_ingredients": ["蒜", "油", "盐"],
                    "cooking_steps": ["锅中热油", "加入食材翻炒", "加盐调味即可"],
                    "estimated_time": "10分钟",
                    "difficulty": "简单",
                    "waste_tip": "任何临期蔬菜都可以用这个方法快速消耗。",
                }
            ]
        recipes = []
        for ing in ingredients[:3]:
            recipes.append({
                "recipe_name": f"{ing}快手料理",
                "core_expiring_food": [ing],
                "other_ingredients": ["油", "盐", "葱", "姜"],
                "cooking_steps": [
                    f"准备{ing}并清洗干净",
                    "热锅下油，加入葱姜爆香",
                    f"加入{ing}翻炒至熟",
                    "加盐调味即可出锅",
                ],
                "estimated_time": "15分钟",
                "difficulty": "简单",
                "waste_tip": f"{ing}临期时最适合快速烹饪消耗，不要等到变质再处理。",
            })
        return recipes

    def _fallback_level2(self, expiring_food_list: list[dict]) -> dict:
        """Level-2 fallback: LLM completely unavailable, show plain text."""
        names = [item.get("name", "") for item in expiring_food_list if item.get("name")]
        name_str = "、".join(names) if names else "一些食材"
        return {
            "recipe_recommend": None,
            "isFallback": True,
            "fallbackText": f"已为你筛选出临期食材：{name_str}，建议优先食用；你可以告诉我想吃的菜品类型，我来为你推荐做法～",
        }


llm_service = LLMService()
