"""Shopping-list capability, separate from owned inventory."""

from uuid import uuid4

from app.db.sqlite import connect
from app.models.state import AgentAction
from app.services.capabilities import BaseCapability, CapabilityRegistry


class ShoppingCapability(BaseCapability):
    name = "shopping"
    description = "家庭采购清单管理"

    def can_handle(self, action: AgentAction) -> bool:
        return action.capability == self.name

    def execute(self, action: AgentAction, context: dict) -> dict:
        entities = action.arguments.get("extracted_entities", {})
        title = str(entities.get("target", "")).strip()
        list_name = str(entities.get("list_name", "采购清单")).strip() or "采购清单"
        count = max(1, int(entities.get("count", 1)))
        unit = str(entities.get("unit", "个")).strip() or "个"
        user_id = context.get("user_id", "default_user")

        if not title:
            return {"mutation_logs": [], "reply_text": "没有识别出要加入采购清单的商品。"}

        with connect() as conn:
            conn.execute(
                """INSERT INTO shopping_list_items(id, list_name, title, quantity, unit, added_by, status)
                   VALUES(?, ?, ?, ?, ?, ?, 'pending')
                   ON CONFLICT(list_name, title, status) DO UPDATE SET
                       quantity=shopping_list_items.quantity + excluded.quantity,
                       unit=excluded.unit,
                       added_by=excluded.added_by,
                       updated_at=CURRENT_TIMESTAMP""",
                (f"shopping-{uuid4().hex[:12]}", list_name, title, count, unit, user_id),
            )

        return {
            "result": {"title": title, "listName": list_name, "count": count, "unit": unit},
            "mutation_logs": [],
            "reply_text": f"已将「{title}」加入{list_name}。",
        }


CapabilityRegistry.register(ShoppingCapability())
