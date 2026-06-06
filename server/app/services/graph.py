from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.models.schemas import Item, RecipeRequest
from app.services.markdown import item_status
from app.services.parser import parse_lightning_text

Intent = Literal["ingest", "expiry_query", "location_query", "recipe", "chat"]


class SquirrelGraphState(TypedDict, total=False):
    text: str
    intent: Intent
    inventory: list[Item]
    parsed_items: list[Item]
    reply_text: str
    recipe: dict


def classify_intent(state: SquirrelGraphState) -> SquirrelGraphState:
    text = state.get("text", "")
    base = {"text": text, "inventory": state.get("inventory", [])}
    ingest_words = ["买了", "购入", "新增", "存入", "录入", "添加", "放", "吃完", "用完", "扔掉", "坏了"]
    if any(word in text for word in ingest_words):
        return {**base, "intent": "ingest"}
    if any(word in text for word in ["过期", "快坏", "临期", "告急"]):
        return {**base, "intent": "expiry_query"}
    if any(word in text for word in ["在哪", "哪里", "放哪", "位置"]):
        return {**base, "intent": "location_query"}
    if any(word in text for word in ["吃什么", "做什么", "菜谱", "做饭"]):
        return {**base, "intent": "recipe"}
    return {**base, "intent": "chat"}


def route_by_intent(state: SquirrelGraphState) -> Intent:
    return state.get("intent", "chat")


def parse_inventory_node(state: SquirrelGraphState) -> SquirrelGraphState:
    parsed = parse_lightning_text(state.get("text", ""))
    if not parsed:
        return {
            "parsed_items": [],
            "reply_text": "我没有识别出明确物品，可以换一种说法再试一次。",
        }
    names = "、".join(item.title for item in parsed)
    return {
        "parsed_items": parsed,
        "reply_text": f"已识别出 {len(parsed)} 件物品：{names}。请确认后入库。",
    }


def expiry_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    inventory = state.get("inventory", [])
    danger = [item for item in inventory if item_status(item) == "danger"]
    if not danger:
        return {"reply_text": "当前没有红色告急或过期预警物品。"}
    summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in danger[:6])
    return {"reply_text": f"现在最需要优先处理的是：{summary}。"}


def location_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    text = state.get("text", "")
    inventory = state.get("inventory", [])
    candidates = [
        item
        for item in inventory
        if item.title in text or text in item.title or item.location in text or item.spaceName in text
    ]
    if not candidates:
        return {"reply_text": "我暂时没在库存里精确匹配到位置，可以试试输入更具体的物品名。"}
    item = candidates[0]
    return {"reply_text": f"{item.title} 在 {item.spaceName} / {item.location}，当前剩余 {item.remainingPct}%。"}


def recipe_node(state: SquirrelGraphState) -> SquirrelGraphState:
    request = RecipeRequest(inventory=state.get("inventory", []))
    candidates = [item for item in request.inventory if item.spaceName in ("主厨房", "主冰箱")]
    urgent = next((item for item in candidates if item_status(item) != "full"), None)
    urgent = urgent or (candidates[0] if candidates else None)
    if not urgent:
        recipe = {
            "title": "清爽库存拼盘",
            "description": "当前厨房库存较稳，可以选择现有食材做轻量整理餐。",
            "ingredients": "现有食材适量，常备调味料少许",
            "steps": ["检查食材状态", "清洗切配", "按口味凉拌或快速加热"],
        }
    else:
        recipe = {
            "title": f"{urgent.title}快手消耗餐",
            "description": f"优先消耗 {urgent.title}，减少临期浪费。",
            "ingredients": f"{urgent.title} {urgent.count}{urgent.unit}，常备调味料适量",
            "steps": ["确认食材没有变质", "清洗并简单处理", "中火快速烹调或搭配主食食用"],
        }
    return {"recipe": recipe, "reply_text": recipe["description"]}


def chat_node(state: SquirrelGraphState) -> SquirrelGraphState:
    inventory = state.get("inventory", [])
    return {"reply_text": f"我查到当前共有 {len(inventory)} 件库存。你可以让我录入、查位置、列临期或生成菜谱。"}


def build_squirrel_graph():
    graph = StateGraph(SquirrelGraphState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("ingest", parse_inventory_node)
    graph.add_node("expiry_query", expiry_query_node)
    graph.add_node("location_query", location_query_node)
    graph.add_node("recipe", recipe_node)
    graph.add_node("chat", chat_node)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "ingest": "ingest",
            "expiry_query": "expiry_query",
            "location_query": "location_query",
            "recipe": "recipe",
            "chat": "chat",
        },
    )
    graph.add_edge("ingest", END)
    graph.add_edge("expiry_query", END)
    graph.add_edge("location_query", END)
    graph.add_edge("recipe", END)
    graph.add_edge("chat", END)
    return graph.compile()


squirrel_graph = build_squirrel_graph()


def run_squirrel_graph(text: str, inventory: list[Item] | None = None) -> SquirrelGraphState:
    return squirrel_graph.invoke({"text": text, "inventory": inventory or []})
