"""BatchCapability — 批量操作处理器。"""

import logging
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4

from app.models.state import ActionStatus, AgentAction
from app.services.capabilities import BaseCapability, CapabilityRegistry

logger = logging.getLogger(__name__)


class BatchCapability(BaseCapability):
    """批量操作能力域 — 处理批量添加、批量消耗、批量删除。"""

    name = "batch"
    description = "批量操作：批量添加/消耗/删除物品"

    def can_handle(self, action: AgentAction) -> bool:
        return action.capability == "batch"

    def validate(self, action: AgentAction, context: Dict[str, Any]) -> List[str]:
        errors = []
        args = action.arguments
        items = args.get("items", [])
        if not items:
            errors.append("批量操作至少需要一件物品")
        if len(items) > 50:
            errors.append("单次批量操作最多 50 件物品")
        return errors

    def execute(self, action: AgentAction, context: Dict[str, Any]) -> Dict[str, Any]:
        intent = action.arguments.get("intent", "")
        entities = action.arguments.get("extracted_entities", {})
        inventory = context.get("inventory", [])
        user_id = context.get("user_id", "default")
        user_name = context.get("user_name", "主人")

        handler_map = {
            "add": self._handle_batch_add,
        }

        handler = handler_map.get(intent)
        if not handler:
            return {
                "result": None,
                "mutation_logs": [],
                "reply_text": f"不支持的批量操作: {intent}",
            }

        return handler(entities, inventory, user_id, user_name)

    def _handle_batch_add(self, entities: dict, inventory: list, user_id: str, user_name: str) -> dict:
        items_data = entities.get("items", [])
        if not items_data:
            return {
                "result": None,
                "mutation_logs": [],
                "reply_text": "没有待添加的物品数据。",
            }

        mutation_logs = []
        for item_dict in items_data:
            mutation_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": "add",
                "target_instance_id": f"new_{uuid4().hex[:12]}",
                "sku_title": item_dict.get("title", "未知物品"),
                "delta": item_dict.get("count", 1),
                "item_data": item_dict,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })

        return {
            "result": {"added_count": len(mutation_logs)},
            "mutation_logs": mutation_logs,
            "reply_text": f"批量添加成功！已录入 {len(mutation_logs)} 件物品。",
            "pending_add_items": items_data,
        }


# 注册
CapabilityRegistry.register(BatchCapability())