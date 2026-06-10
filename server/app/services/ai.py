from app.models.schemas import ChatResult, Item, RecipeRequest
from app.services.graph import run_squirrel_graph


class AiService:
    def parse_inventory_command(self, text: str) -> list[Item]:
        result = run_squirrel_graph(text)
        chat_result = result.get("chat_result")
        if not chat_result:
            return result.get("parsed_items", [])
        return [operation.item for operation in chat_result.operations if operation.type == "add" and operation.item]

    def chat(self, text: str, inventory: list[Item]) -> ChatResult:
        result = run_squirrel_graph(text, inventory)
        return result.get("chat_result", ChatResult())

    def recipe(self, request: RecipeRequest, inventory: list[Item]) -> dict:
        result = run_squirrel_graph("菜谱", request.inventory or inventory)
        return result.get("recipe", {})


ai_service = AiService()
