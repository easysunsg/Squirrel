import logging
from typing import TypedDict

from app.models.schemas import ChatOperation, ChatResult, Item, RecipeRequest
from app.services.llm import llm_service
from app.services.markdown import item_status
from app.services.parser import build_chat_result, extract_remaining_patch, extract_search_keyword, infer_search_terms, parse_lightning_text
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)


class SquirrelGraphState(TypedDict, total=False):
    text: str
    inventory: list[Item]
    chat_result: ChatResult
    recipe: dict


def summarize_titles(items: list[Item], limit: int = 6) -> str:
    return "、".join(item.title for item in items[:limit])


def match_search_items(text: str, inventory: list[Item]) -> list[Item]:
    query = extract_search_keyword(text)
    results = vector_store.search(query, inventory)
    if results:
        return results
    terms = infer_search_terms(text)
    if not terms:
        return []
    matched: list[Item] = []
    for item in inventory:
        haystacks = [item.title, item.location, item.spaceName, item.remark or ""]
        if any(term and any(term in value for value in haystacks) for term in terms):
            matched.append(item)
    return matched[:8]


def classify_intent(state: SquirrelGraphState) -> SquirrelGraphState:
    """Classify user intent using LLM with rule-based fallback."""
    text = state.get("text", "")
    inventory = state.get("inventory", [])

    # Try LLM first
    if llm_service.enabled:
        try:
            inventory_summary = summarize_titles(inventory, limit=10) if inventory else "库存为空"
            llm_result = llm_service.classify_intent(text, inventory_summary)
            intent = llm_result.get("intent", "unknown")
            entities = llm_result.get("entities", {})

            if intent != "unknown":
                # Build ChatResult from LLM output
                chat_result = ChatResult(intent=intent, replyText=f"已识别意图：{intent}")

                # Convert entities to operations
                if intent == "add":
                    # Use rule-based parser for item extraction (more reliable for structured input)
                    parsed_items = parse_lightning_text(text)
                    chat_result.operations = [ChatOperation(type="add", item=item) for item in parsed_items]
                    chat_result.replyText = f"已识别出 {len(parsed_items)} 件物品，准备入库。"
                elif intent == "consume" or intent == "remove":
                    target = entities.get("target")
                    chat_result.operations = [ChatOperation(
                        type=intent,
                        target=target,
                        patch={"remainingPct": entities.get("remaining_pct"), "count": entities.get("count")} if intent == "consume" and entities.get("remaining_pct") is not None else None,
                    )]
                elif intent == "update_location":
                    target = entities.get("target")
                    location = entities.get("location")
                    if target and location:
                        chat_result.operations = [ChatOperation(type="update", target=target, patch={"location": location})]
                elif intent == "update_expiry":
                    target = entities.get("target")
                    expire_days = entities.get("expire_days")
                    if target and expire_days is not None:
                        from app.services.parser import days_from_now
                        chat_result.operations = [ChatOperation(type="update", target=target, patch={"expireDate": days_from_now(expire_days)})]

                logger.info("LLM intent classification succeeded intent=%s", intent)
                return {
                    "text": text,
                    "inventory": inventory,
                    "chat_result": chat_result,
                }
        except Exception:
            logger.exception("LLM intent classification failed, falling back to rules")

    # Fallback to rule-based
    return {
        "text": text,
        "inventory": inventory,
        "chat_result": build_chat_result(text),
    }


def route_by_intent(state: SquirrelGraphState) -> str:
    return state.get("chat_result", ChatResult()).intent


def add_node(state: SquirrelGraphState) -> SquirrelGraphState:
    chat_result = state["chat_result"]
    if chat_result.operations:
        item_count = len([op for op in chat_result.operations if op.type == "add" and op.item])
        if item_count > 0:
            chat_result.needsConfirmation = True
            chat_result.replyText = f"已识别出 {item_count} 件物品，请确认后再入库。"
    return {"chat_result": chat_result}


def consume_node(state: SquirrelGraphState) -> SquirrelGraphState:
    text = state.get("text", "")
    operations = state["chat_result"].operations
    inventory = state.get("inventory", [])
    if not operations:
        return {"chat_result": ChatResult(intent="consume", replyText="我没识别到要消耗的物品。")}
    target = operations[0].target
    item = next((candidate for candidate in inventory if target and target in candidate.title), None)
    if not item:
        return {
            "chat_result": ChatResult(
                intent="consume",
                replyText="我暂时没找到对应物品，请说得更具体一点。",
                needsConfirmation=True,
            )
        }
    patch = extract_remaining_patch(text, item)
    if not patch:
        patch = {"remainingPct": 0, "count": 0}
    operation_type = "remove" if patch.get("remainingPct") == 0 and patch.get("count", item.count) == 0 else "consume"
    return {
        "chat_result": ChatResult(
            intent="consume",
            replyText="已识别到消耗操作。",
            operations=[
                ChatOperation(
                    type=operation_type,
                    target=item.title,
                    patch=patch if operation_type == "consume" else None,
                    consumeAll=operation_type == "remove",
                )
            ],
        )
    }


def remove_node(state: SquirrelGraphState) -> SquirrelGraphState:
    return {"chat_result": state["chat_result"]}


def update_location_node(state: SquirrelGraphState) -> SquirrelGraphState:
    return {"chat_result": state["chat_result"]}


def update_expiry_node(state: SquirrelGraphState) -> SquirrelGraphState:
    return {"chat_result": state["chat_result"]}


def update_remaining_node(state: SquirrelGraphState) -> SquirrelGraphState:
    return {"chat_result": state["chat_result"]}


def expiry_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    inventory = state.get("inventory", [])
    danger = [item for item in inventory if item_status(item) == "danger"]
    if not danger:
        return {"chat_result": ChatResult(intent="expiry_query", replyText="当前没有红色告急或过期预警物品。")}
    summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in danger[:6])
    return {"chat_result": ChatResult(intent="expiry_query", replyText=f"现在最需要优先处理的是：{summary}。")}


def location_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    text = state.get("text", "")
    inventory = state.get("inventory", [])
    candidates = [
        item
        for item in inventory
        if item.title in text or text in item.title or item.location in text or item.spaceName in text
    ]
    if not candidates:
        return {
            "chat_result": ChatResult(
                intent="location_query",
                replyText="我暂时没在库存里精确匹配到位置，可以试试输入更具体的物品名。",
            )
        }
    item = candidates[0]
    return {
        "chat_result": ChatResult(
            intent="location_query",
            replyText=f"{item.title} 在 {item.spaceName} / {item.location}，当前剩余 {item.remainingPct}%。",
        )
    }


def search_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    text = state.get("text", "")
    inventory = state.get("inventory", [])
    matches = match_search_items(text, inventory)
    if not matches:
        return {"chat_result": ChatResult(intent="search_query", replyText="我暂时没搜到相关库存。")}
    summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in matches[:6])
    return {
        "chat_result": ChatResult(
            intent="search_query",
            replyText=f"我找到这些相关物品：{summary}。",
            itemSuggestion={"matches": [item.model_dump() for item in matches[:6]]},
        )
    }


def idle_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    inventory = state.get("inventory", [])
    idle = sorted(
        [item for item in inventory if item.remainingPct >= 80 and item_status(item) == "full"],
        key=lambda item: item.buyDate or "",
    )
    if not idle:
        return {"chat_result": ChatResult(intent="idle_query", replyText="当前没有明显长期闲置的物品。")}
    summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in idle[:6])
    return {"chat_result": ChatResult(intent="idle_query", replyText=f"这些物品可能放了比较久：{summary}。")}


def recipe_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """Generate recipe using LLM with rule-based fallback."""
    inventory = state.get("inventory", [])
    candidates = [item for item in inventory if item.spaceName in ("主厨房", "主冰箱")]
    urgent = next((item for item in candidates if item_status(item) != "full"), None)
    urgent = urgent or (candidates[0] if candidates else None)

    # Try LLM generation
    if llm_service.enabled:
        try:
            ingredients = [item.title for item in candidates[:10]]
            urgent_item = urgent.title if urgent else None
            recipe = llm_service.generate_recipe(ingredients, urgent_item)
            logger.info("LLM recipe generation succeeded title=%s", recipe.get("title"))
            return {
                "chat_result": ChatResult(intent="recipe", replyText=recipe["description"]),
                "recipe": recipe,
            }
        except Exception:
            logger.exception("LLM recipe generation failed, falling back to template")

    # Fallback to template
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
    return {
        "chat_result": ChatResult(intent="recipe", replyText=recipe["description"]),
        "recipe": recipe,
    }


def chat_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """Handle general chat using LLM with rule-based fallback."""
    text = state.get("text", "")
    inventory = state.get("inventory", [])

    # Build context summary
    context_parts = [f"库存总数：{len(inventory)} 件"]
    danger = [item for item in inventory if item_status(item) == "danger"]
    if danger:
        context_parts.append(f"临期/告急：{len(danger)} 件")

    context = "；".join(context_parts)

    # Try LLM chat
    if llm_service.enabled:
        try:
            reply = llm_service.chat_reply(text, context)
            logger.info("LLM chat reply succeeded")
            return {
                "chat_result": ChatResult(intent="chat", replyText=reply)
            }
        except Exception:
            logger.exception("LLM chat reply failed, falling back to template")

    # Fallback to template
    return {
        "chat_result": ChatResult(
            intent="chat",
            replyText=f"我查到当前共有 {len(inventory)} 件库存。你可以让我录入、查位置、列临期或生成菜谱。",
        )
    }


def build_squirrel_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(SquirrelGraphState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("add", add_node)
    graph.add_node("consume", consume_node)
    graph.add_node("remove", remove_node)
    graph.add_node("update_location", update_location_node)
    graph.add_node("update_expiry", update_expiry_node)
    graph.add_node("update_remaining", update_remaining_node)
    graph.add_node("expiry_query", expiry_query_node)
    graph.add_node("location_query", location_query_node)
    graph.add_node("search_query", search_query_node)
    graph.add_node("idle_query", idle_query_node)
    graph.add_node("recipe", recipe_node)
    graph.add_node("chat", chat_node)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "add": "add",
            "consume": "consume",
            "remove": "remove",
            "update_location": "update_location",
            "update_expiry": "update_expiry",
            "update_remaining": "update_remaining",
            "expiry_query": "expiry_query",
            "location_query": "location_query",
            "search_query": "search_query",
            "idle_query": "idle_query",
            "recipe": "recipe",
            "chat": "chat",
        },
    )
    for node in [
        "add",
        "consume",
        "remove",
        "update_location",
        "update_expiry",
        "update_remaining",
        "expiry_query",
        "location_query",
        "search_query",
        "idle_query",
        "recipe",
        "chat",
    ]:
        graph.add_edge(node, END)
    return graph.compile()


squirrel_graph = build_squirrel_graph()


def run_squirrel_graph(text: str, inventory: list[Item] | None = None) -> SquirrelGraphState:
    return squirrel_graph.invoke({"text": text, "inventory": inventory or []})
