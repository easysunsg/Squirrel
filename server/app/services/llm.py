"""LLM service for intelligent parsing and generation."""

import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Wrapper for LLM API calls with fallback to rule-based parsing."""

    def __init__(self):
        self.provider = settings.ai_provider
        self.api_key = settings.ai_api_key
        self.base_url = settings.ai_base_url
        self.model = settings.ai_model
        self.enabled = self.provider != "mock" and bool(self.api_key)

        if self.enabled:
            logger.info(
                "LLM service initialized provider=%s model=%s base_url=%s",
                self.provider,
                self.model,
                self.base_url,
            )
        else:
            logger.info("LLM service disabled, using rule-based fallback")

    def _call_openai_compatible(self, messages: list[dict], response_format: dict | None = None) -> str:
        """Call OpenAI-compatible API."""
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,
            }

            if response_format:
                payload["response_format"] = response_format

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip()
        except Exception:
            logger.exception("LLM API call failed")
            raise

    def classify_intent(
        self,
        text: str,
        inventory_summary: str = "",
    ) -> dict:
        """Classify user intent with LLM.

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

        user_prompt = f"""用户输入：{text}

当前库存摘要：{inventory_summary or "无"}

请分析意图并提取实体。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._call_openai_compatible(
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
            response = self._call_openai_compatible(
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
            response = self._call_openai_compatible(messages)
            logger.info("Chat reply generated for message=%r", user_message)
            return response
        except Exception:
            logger.exception("Chat reply generation failed, using fallback")
            return "我理解你的意思了。你可以让我录入物品、查位置、列临期或生成菜谱。"


llm_service = LLMService()
