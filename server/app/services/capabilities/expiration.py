"""ExpirationCapability — 临期查询与过期预警。"""

import logging
from datetime import datetime, date
from typing import Any, Dict, List

from app.models.state import ActionStatus, AgentAction
from app.services.capabilities import BaseCapability, CapabilityRegistry

logger = logging.getLogger(__name__)


class ExpirationCapability(BaseCapability):
    """临期管理能力域 — 处理所有保质期相关查询和预警。"""

    name = "expiration"
    description = "临期管理：查询过期物品、临期预警"

    def can_handle(self, action: AgentAction) -> bool:
        return action.capability == "expiration"

    def execute(self, action: AgentAction, context: Dict[str, Any]) -> Dict[str, Any]:
        intent = action.arguments.get("intent", "")
        entities = action.arguments.get("extracted_entities", {})
        inventory = context.get("inventory", [])

        if intent == "expiry_query":
            return self._handle_expiry_query(entities, inventory)

        return {
            "result": None,
            "mutation_logs": [],
            "reply_text": f"不支持的临期操作: {intent}",
        }

    def _handle_expiry_query(self, entities: dict, inventory: list, days_threshold: int = 7) -> dict:
        """查询临期/过期物品。"""
        from app.services.markdown import item_status

        today = date.today()
        expiring_items = []

        for item in inventory:
            st = item_status(item)
            if st == "danger":
                expire_days = None
                if item.expireDate:
                    try:
                        expire_dt = datetime.strptime(item.expireDate, "%Y-%m-%d").date()
                        expire_days = (expire_dt - today).days
                    except (ValueError, TypeError):
                        pass
                expiring_items.append({
                    "title": item.title,
                    "location": f"{item.spaceName}/{item.location}",
                    "expire_date": item.expireDate or "未知",
                    "expire_days": expire_days,
                    "remaining_pct": item.remainingPct,
                })

        if not expiring_items:
            return {
                "result": {"expiring_items": []},
                "mutation_logs": [],
                "reply_text": "当前没有红色告急或过期预警物品，库存状态良好！",
            }

        # 按紧迫程度排序
        expiring_items.sort(key=lambda x: (x["expire_days"] if x["expire_days"] is not None else 9999))
        summary = "、".join(
            f"{it['title']}（{it['location']}）" + (f" 剩余{it['expire_days']}天" if it['expire_days'] is not None else "")
            for it in expiring_items[:6]
        )

        return {
            "result": {"expiring_items": expiring_items},
            "mutation_logs": [],
            "reply_text": f"现在最需要优先处理的是：{summary}。",
        }


# 注册
CapabilityRegistry.register(ExpirationCapability())