"""InventoryCapability — 物资入库/出库/扣减/查询/更新操作。

包含：
- add: 新增物品
- consume: 消耗物品
- remove: 移除物品
- update_location: 更新位置
- update_expiry: 更新保质期
- update_remaining: 更新剩余量
- location_query / quantity_query / search_query: 查询
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.models.schemas import Item
from app.models.state import ActionStatus, AgentAction
from app.services.capabilities import BaseCapability, CapabilityRegistry
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)

_SUPPORTED_TOOLS = {
    "inventory_add", "inventory_consume", "inventory_remove",
    "inventory_update_location", "inventory_update_expiry", "inventory_update_remaining",
    "inventory_location_query", "inventory_quantity_query", "inventory_search_query",
}


class InventoryCapability(BaseCapability):
    """库存管理能力域 — 处理所有物资相关的增删改查操作。"""

    name = "inventory"
    description = "库存管理：添加、消耗、移除、更新、查询物品"

    def can_handle(self, action: AgentAction) -> bool:
        return action.capability == "inventory"

    def validate(self, action: AgentAction, context: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        args = action.arguments
        target = args.get("target", "")
        intent = args.get("intent", "")

        if intent in ("consume", "remove", "update_location", "update_expiry"):
            if not target:
                errors.append("缺少目标物品名称")
            if intent == "update_location" and not args.get("location") and not (args.get("extracted_entities", {}).get("patch") or {}).get("location"):
                errors.append("缺少目标位置")

        return errors

    def execute(self, action: AgentAction, context: Dict[str, Any]) -> Dict[str, Any]:
        intent = action.arguments.get("intent", "")
        entities = action.arguments.get("extracted_entities", {})
        inventory = context.get("inventory", [])
        user_id = context.get("user_id", "default")
        user_name = context.get("user_name", "主人")

        handler_map = {
            "add": self._handle_add,
            "consume": self._handle_consume,
            "remove": self._handle_remove,
            "update_location": self._handle_update_location,
            "update_expiry": self._handle_update_expiry,
            "update_remaining": self._handle_update_remaining,
            "location_query": self._handle_location_query,
            "quantity_query": self._handle_quantity_query,
            "search_query": self._handle_search_query,
        }

        handler = handler_map.get(intent)
        if not handler:
            return {
                "result": None,
                "mutation_logs": [],
                "reply_text": f"不支持的意图: {intent}",
            }

        return handler(entities, inventory, user_id, user_name, context)

    def _handle_add(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        items_data = entities.get("items", [])
        target = entities.get("target", "物品")

        mutation_logs = []
        for item_dict in items_data:
            if isinstance(item_dict, dict):
                mutation_logs.append({
                    "event_id": f"evt_{datetime.now().timestamp()}",
                    "op_type": "add",
                    "target_instance_id": f"new_{uuid4().hex[:12]}",
                    "sku_title": item_dict.get("title", target),
                    "delta": item_dict.get("count", 1),
                    "item_data": item_dict,
                    "operator_id": user_id,
                    "operator_name": user_name,
                    "timestamp": datetime.now().isoformat(),
                })

        return {
            "result": {"added_count": len(mutation_logs)},
            "mutation_logs": mutation_logs,
            "reply_text": f"登记成功！已帮您将{len(mutation_logs)}件物品录入系统。",
            "pending_add_items": items_data,
        }

    def _handle_consume(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        target = entities.get("target", "")
        pending_op = context.get("pending_operation")
        mutation_logs = []
        reply_text = ""

        if pending_op and pending_op.source_batch_ids:
            deduct_counts = (pending_op.patch or {}).get("deductCounts", {})
            for batch_id in pending_op.source_batch_ids:
                matched = [it for it in inventory if it.id == batch_id]
                if matched:
                    item = matched[0]
                    actual_deduct = deduct_counts.get(batch_id, 1) if deduct_counts else 1
                    mutation_logs.append({
                        "event_id": f"evt_{datetime.now().timestamp()}",
                        "op_type": "consume",
                        "target_instance_id": batch_id,
                        "sku_title": item.title,
                        "delta": -actual_deduct,
                        "operator_id": user_id,
                        "operator_name": user_name,
                        "timestamp": datetime.now().isoformat(),
                    })
        else:
            patch = entities.get("patch") or {}
            deduct_count = patch.get("deductCount") or 1
            matched = [it for it in inventory if it.title == target]
            for item in matched[:1]:
                mutation_logs.append({
                    "event_id": f"evt_{datetime.now().timestamp()}",
                    "op_type": "consume",
                    "target_instance_id": item.id,
                    "sku_title": item.title,
                    "delta": -deduct_count,
                    "operator_id": user_id,
                    "operator_name": user_name,
                    "timestamp": datetime.now().isoformat(),
                })

        if not reply_text:
            reply_text = f"好滴{user_name}，已帮您处理了 **{target}**。" if target else "已处理完成。"

        return {
            "result": {"consumed_count": len(mutation_logs)},
            "mutation_logs": mutation_logs,
            "reply_text": reply_text,
        }

    def _handle_remove(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        pending_op = context.get("pending_operation")
        confirmed_ids = context.get("confirmed_item_ids", [])
        mutation_logs = []

        if confirmed_ids:
            for item_id in confirmed_ids:
                matched = [it for it in inventory if it.id == item_id]
                if matched:
                    mutation_logs.append({
                        "event_id": f"evt_{datetime.now().timestamp()}",
                        "op_type": "remove",
                        "target_instance_id": item_id,
                        "sku_title": matched[0].title,
                        "delta": -(matched[0].count or 1),
                        "operator_id": user_id,
                        "operator_name": user_name,
                        "timestamp": datetime.now().isoformat(),
                    })
        elif pending_op and pending_op.source_batch_ids:
            for batch_id in pending_op.source_batch_ids:
                matched = [it for it in inventory if it.id == batch_id]
                if matched:
                    mutation_logs.append({
                        "event_id": f"evt_{datetime.now().timestamp()}",
                        "op_type": "remove",
                        "target_instance_id": batch_id,
                        "sku_title": matched[0].title,
                        "delta": -(matched[0].count or 1),
                        "operator_id": user_id,
                        "operator_name": user_name,
                        "timestamp": datetime.now().isoformat(),
                    })

        return {
            "result": {"removed_count": len(mutation_logs)},
            "mutation_logs": mutation_logs,
            "reply_text": f"已移除 {len(mutation_logs)} 件物品。",
        }

    def _handle_update_location(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        target = entities.get("target", "")
        patch = entities.get("patch") or {}
        location = patch.get("location", entities.get("location", ""))
        mutation_logs = []

        matched = [it for it in inventory if it.title == target]
        for item in matched[:1]:
            mutation_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": "update",
                "target_instance_id": item.id,
                "sku_title": item.title,
                "patch": {"location": location},
                "delta": 0,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })

        return {
            "result": {"updated_count": len(mutation_logs)},
            "mutation_logs": mutation_logs,
            "reply_text": f"已将「{target}」的位置更新为：{location}" if target and location else "位置已更新。",
        }

    def _handle_update_expiry(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        target = entities.get("target", "")
        patch = entities.get("patch") or {}
        expire_date = patch.get("expireDate", "")
        mutation_logs = []

        matched = [it for it in inventory if it.title == target]
        for item in matched[:1]:
            mutation_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": "update",
                "target_instance_id": item.id,
                "sku_title": item.title,
                "patch": {"expireDate": expire_date},
                "delta": 0,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })

        return {
            "result": {"updated_count": len(mutation_logs)},
            "mutation_logs": mutation_logs,
            "reply_text": f"「{target}」的保质期已更新。" if target else "保质期已更新。",
        }

    def _handle_update_remaining(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        target = entities.get("target", "")
        patch = entities.get("patch") or {}
        remaining_pct = patch.get("remainingPct", 100)
        mutation_logs = []

        matched = [it for it in inventory if it.title == target]
        for item in matched[:1]:
            mutation_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": "update",
                "target_instance_id": item.id,
                "sku_title": item.title,
                "patch": {"remainingPct": remaining_pct},
                "delta": 0,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })

        return {
            "result": {"updated_count": len(mutation_logs)},
            "mutation_logs": mutation_logs,
            "reply_text": f"「{target}」的剩余量已更新为 {remaining_pct}%。" if target else "剩余量已更新。",
        }

    def _handle_location_query(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        target = entities.get("target", "")
        matched = [it for it in inventory if it.title == target or (target and target in it.title)]
        if not matched:
            return {"result": None, "mutation_logs": [], "reply_text": f"没有找到「{target}」的位置信息。"}
        item = matched[0]
        return {
            "result": {"item": item, "location": item.location},
            "mutation_logs": [],
            "reply_text": f"{item.title} 在 {item.spaceName} / {item.location}，当前剩余 {item.remainingPct}%。",
        }

    def _handle_quantity_query(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        target = entities.get("target", "")
        matched = [it for it in inventory if it.title == target]
        if not matched:
            return {"result": None, "mutation_logs": [], "reply_text": f"没有找到「{target}」的数量信息。"}
        item = matched[0]
        return {
            "result": {"item": item, "quantity": item.count},
            "mutation_logs": [],
            "reply_text": f"「{item.title}」还剩 {item.count}{item.unit}，在 {item.spaceName}{item.location}。",
        }

    def _handle_search_query(self, entities: dict, inventory: list, user_id: str, user_name: str, context: dict) -> dict:
        target = entities.get("target", "")
        matched = [it for it in inventory if target in it.title or target in it.location or (it.remark and target in it.remark)]
        if not matched:
            return {"result": None, "mutation_logs": [], "reply_text": "没有找到匹配的物品。"}
        summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in matched[:6])
        return {
            "result": {"items": matched[:8]},
            "mutation_logs": [],
            "reply_text": f"搜索到以下物品：{summary}。",
        }


# 注册到全局注册表
CapabilityRegistry.register(InventoryCapability())