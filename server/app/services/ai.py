from app.models.schemas import Item, RecipeRequest
from app.services.graph import run_squirrel_graph


class AiService:
    def parse_inventory_command(self, text: str) -> list[Item]:
        result = run_squirrel_graph(text)
        return result.get("parsed_items", [])

    def chat(self, text: str, inventory: list[Item]) -> str:
        result = run_squirrel_graph(text, inventory)
        return result.get("reply_text", "我已经处理完这次请求。")

    def recipe(self, request: RecipeRequest, inventory: list[Item]) -> dict:
        result = run_squirrel_graph("菜谱", request.inventory or inventory)
        return result.get("recipe", {})


ai_service = AiService()
