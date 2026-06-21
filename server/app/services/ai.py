from app.models.schemas import ChatResult, Item, RecipeRequest
from app.services.graph import run_squirrel_graph


class AiService:
    def parse_inventory_command(self, text: str) -> list[Item]:
        result = run_squirrel_graph(text)
        chat_result = result.get("chat_result")
        if not chat_result:
            return result.get("parsed_items", [])
        return [operation.item for operation in chat_result.operations if operation.type == "add" and operation.item]

    def chat(
        self,
        text: str,
        inventory: list[Item],
        interaction_mode: str = "normal",
        pending_item_selection: list | None = None,
        pending_operation: dict | None = None,
        last_added_item: dict | None = None,
        current_context_item: dict | None = None,
    ) -> dict:
        return run_squirrel_graph(
            text,
            inventory,
            interaction_mode=interaction_mode,
            pending_item_selection=pending_item_selection,
            pending_operation=pending_operation,
            last_added_item=last_added_item,
            current_context_item=current_context_item,
        )

    def recipe(self, request: RecipeRequest, inventory: list[Item]) -> dict:
        # Build user_preference from system preferences
        pref = "无特殊要求"
        reminder_time = ""
        if request.systemPreferences:
            habits = request.systemPreferences.allergies or []
            pref = "、".join(habits) if habits else "无特殊要求"
            reminder_time = request.systemPreferences.reminderTime or ""

        result = run_squirrel_graph(
            "菜谱",
            inventory=request.inventory or inventory,
            user_preference=pref,
            reminder_time=reminder_time,
        )
        return result.get("recipe_recommend", result.get("recipe", {}))


ai_service = AiService()
