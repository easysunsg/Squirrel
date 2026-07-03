"""RecommendationCapability — 食谱推荐与建议生成。"""

import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from app.models.schemas import Item
from app.models.state import ActionStatus, AgentAction
from app.services.cache import get_recipe_cache, set_recipe_cache
from app.services.capabilities import BaseCapability, CapabilityRegistry
from app.services.llm import llm_service
from app.services.markdown import item_status

logger = logging.getLogger(__name__)


def _calc_expire_days(item: Item) -> Optional[int]:
    """计算物品距离过期还有多少天。"""
    if not item.expireDate:
        return None
    try:
        expiry = datetime.strptime(item.expireDate, "%Y-%m-%d").date()
        delta = (expiry - date.today()).days
        return delta
    except (ValueError, TypeError):
        return None


class RecommendationCapability(BaseCapability):
    """推荐能力域 — 食谱推荐、物品使用建议。"""

    name = "recommendation"
    description = "智能推荐：食谱生成、物品使用建议"

    def can_handle(self, action: AgentAction) -> bool:
        return action.capability == "recommendation"

    def validate(self, action: AgentAction, context: Dict[str, Any]) -> List[str]:
        errors = []
        target = action.arguments.get("target", "")
        if not target:
            errors.append("缺少食材名称")
        return errors

    def execute(self, action: AgentAction, context: Dict[str, Any]) -> Dict[str, Any]:
        intent = action.arguments.get("intent", "")
        entities = action.arguments.get("extracted_entities", {})
        inventory = context.get("inventory", [])
        user_pref = context.get("user_preference", "无特殊要求")
        reminder_time = context.get("reminder_time", "")

        if intent == "recipe":
            return self._handle_recipe(entities, inventory, user_pref, reminder_time)

        # chat 意图也走推荐（对话式回复）
        return {
            "result": None,
            "mutation_logs": [],
            "reply_text": "好的，有什么可以帮您推荐的吗？",
        }

    def _handle_recipe(self, entities: dict, inventory: list, user_pref: str, reminder_time: str) -> dict:
        """生成食谱推荐。"""
        target_item_title = entities.get("target", "")

        if not target_item_title:
            return {
                "result": None,
                "mutation_logs": [],
                "reply_text": "您是想用哪些快过期的食材来生成菜单呢？可以告诉我食材名称哦。",
            }

        from app.models.state import _calc_expire_days
        from app.services.graph import _calc_expire_days as calc_days

        expiring_list = []
        for item in inventory:
            if item.category != "food":
                continue
            st = item_status(item)
            expire_days = _calc_expire_days(item)
            if st != "full" or (item.expireDate and expire_days is not None and expire_days <= 7):
                expiring_list.append({
                    "name": item.title,
                    "quantity": item.count,
                    "unit": item.unit,
                    "expire_days": expire_days or 0,
                })

        expiring_list.sort(key=lambda x: (x["expire_days"], -x["quantity"]))
        expiring_list = expiring_list[:10]

        cached = get_recipe_cache(expiring_list, user_pref, reminder_time)
        if cached:
            return {
                "result": {"recipe_recommendation": cached},
                "mutation_logs": [],
                "reply_text": cached.get("recipe_recommend", {}).get("intro", "菜谱已生成"),
                "recipe_recommendation": cached,
            }

        result = llm_service.generate_expiring_recipe(expiring_list, user_pref)
        if not result.get("isFallback") and result.get("recipe_recommend"):
            set_recipe_cache(expiring_list, user_pref, result, reminder_time)

        if result.get("isFallback") and result.get("fallbackText"):
            reply = result["fallbackText"]
        elif result.get("recipe_recommend"):
            reply = result["recipe_recommend"].get("intro", "菜谱已生成")
        else:
            reply = "暂无足够的食材信息生成菜谱，请先添加一些食材到库存吧。"

        return {
            "result": {"recipe_recommendation": result},
            "mutation_logs": [],
            "reply_text": reply,
            "recipe_recommendation": result,
        }


# 注册
CapabilityRegistry.register(RecommendationCapability())