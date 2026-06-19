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
    # === 跨轮次物品选择交互状态（持久化到 SQLite conversation_state 表） ===
    interaction_mode: str          # "normal" | "item_select_confirm"
    pending_item_selection: list   # [{"index":1,"id":"...","title":"...","location":"...","spaceName":"...","count":1,"unit":"个","remainingPct":100,"consumeAll":false}]


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


# ========== 优先路由：检查交互模式 ==========

def route_mode(state: SquirrelGraphState) -> str:
    """最高优先级路由——在意图识别前检查交互模式。

    若 interaction_mode = item_select_confirm，跳过 classify_intent，
    直接进入确认选择 / 重置 / 无效输入节点。
    """
    mode = state.get("interaction_mode", "normal")
    if mode == "item_select_confirm":
        text = state.get("text", "").strip()
        selection = state.get("pending_item_selection", [])
        # 如果输入是非数字的新查询（不是选择响应），自动重置到 normal
        if text and not text.isdigit() and text not in ("取消", "退出", "全部"):
            # 检查是否有可用的 pending_item_selection，如果没有选择项则用户可能已经清空了
            return "classify_intent"
        if text in ("取消", "退出"):
            return "reset_selection"
        if text == "全部" and selection:
            return "confirm_selection_all"
        if text.isdigit() and 1 <= int(text) <= len(selection):
            return "confirm_selection"
        return "invalid_selection"
    return "classify_intent"


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


def _match_items_3tier(inventory: list[Item], target: str | None) -> list[Item]:
    """3-tier matching: exact → substring → location/space."""
    if not target:
        return []
    exact = [item for item in inventory if item.title == target]
    if exact:
        return exact
    partial = [item for item in inventory if target in item.title or item.title in target]
    if partial:
        return partial
    return [item for item in inventory if target in item.location or target in item.spaceName]


def consume_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """消耗节点——匹配物品后设置 pending_item_selection 和 interaction_mode。

    保持 operations 信息不丢，让 execute_chat_operations 能创建 pending_consume 记录。
    """
    text = state.get("text", "")
    operations = state["chat_result"].operations
    inventory = state.get("inventory", [])
    if not operations:
        return {"chat_result": ChatResult(intent="consume", replyText="我没识别到要消耗的物品。")}

    target = operations[0].target
    consume_all = operations[0].consumeAll
    candidates = _match_items_3tier(inventory, target)

    if not candidates:
        return {
            "chat_result": ChatResult(
                intent="consume",
                replyText="我暂时没找到对应物品，请说得更具体一点。",
            )
        }

    # === 限制最多 6 个候选项 ===
    candidates = candidates[:6]

    # 构建待选择列表（包含完整的物品信息和操作）
    pending_selection = []
    for item in candidates:
        # 从 operations[0].patch 提取消耗数量
        deduct_count = None
        if operations and operations[0].patch:
            patch_count = operations[0].patch.get("count")
            if patch_count is not None:
                patch_remaining = operations[0].patch.get("remainingPct")
                if patch_remaining == 0:
                    deduct_count = item.count  # 全部消耗
                elif item.count > 0:
                    deduct_count = item.count - patch_count
        pending_selection.append({
            "id": item.id,
            "title": item.title,
            "spaceName": item.spaceName,
            "location": item.location,
            "count": item.count,
            "unit": item.unit,
            "remainingPct": item.remainingPct,
            "consumeAll": consume_all,
            "deductCount": deduct_count,
        })

    # 生成编号提示文本
    lines = [f"找到 {len(candidates)} 个匹配物品，请回复序号选择："]
    for i, item in enumerate(candidates, 1):
        unit_part = f"{item.count}{item.unit}" if item.count else ""
        lines.append(f"{i}. {item.title} — {item.spaceName}/{item.location} ({unit_part})")
    if consume_all:
        lines.append("回复「全部」将清除所有匹配项")

    return {
        "chat_result": ChatResult(
            intent="consume",
            replyText="\n".join(lines),
            needsConfirmation=True,
            # 保留 operations 让 execute_chat_operations 创建 pending_consume
            operations=operations,
            itemSuggestion={
                "matches": [item.model_dump() for item in candidates],
                "consumeAll": consume_all,
            },
        ),
        "interaction_mode": "item_select_confirm",
        "pending_item_selection": pending_selection,
    }


def remove_node(state: SquirrelGraphState) -> SquirrelGraphState:
    return {"chat_result": state["chat_result"]}


# ========== 序号选择相关节点 ==========

def confirm_selection_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """【新增】用户回复数字序号——匹配 pending_item_selection，返回待删除物品信息。

    不在此处执行数据库操作——返回 confirmedItemId 由路由层执行。
    """
    text = state.get("text", "").strip()
    selection = state.get("pending_item_selection", [])

    index = int(text) - 1  # 用户输入从 1 开始
    if index < 0 or index >= len(selection):
        return {
            "chat_result": ChatResult(
                intent="chat",
                replyText=f"序号超出范围，请回复 1-{len(selection)} 之间的数字，或回复「取消」退出选择。",
            ),
            "interaction_mode": "item_select_confirm",
            "pending_item_selection": selection,
        }

    selected = selection[index]
    item_title = selected.get("title", "")
    consume_all = selected.get("consumeAll", False)
    deduct_count = selected.get("deductCount")

    chat_result = ChatResult(
        intent="consume",
        replyText=f"已确认选择：{item_title}。正在为你处理...",
        needsConfirmation=True,
        confirmedItemId=selected.get("id"),
        confirmedAllItems=consume_all,
    )
    if deduct_count is not None:
        chat_result.confirmedDeductCount = deduct_count

    return {
        "chat_result": chat_result,
        "interaction_mode": "normal",
        "pending_item_selection": None,
    }


def confirm_selection_all_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """【新增】用户回复「全部」——删除所有候选项。"""
    selection = state.get("pending_item_selection", [])
    if not selection:
        return {
            "chat_result": ChatResult(
                intent="chat",
                replyText="没有可清除的物品。",
            ),
            "interaction_mode": "normal",
            "pending_item_selection": None,
        }

    # 返回第一个物品 ID，由路由层循环删除所有匹配项
    first_id = selection[0].get("id")
    first_title = selection[0].get("title", "")

    return {
        "chat_result": ChatResult(
            intent="consume",
            replyText=f"正在清除所有匹配的「{first_title}」物品...",
            needsConfirmation=True,
            confirmedItemId=first_id,
            confirmedAllItems=True,
        ),
        "interaction_mode": "normal",
        "pending_item_selection": None,
    }


def reset_selection_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """【新增】用户输入「取消」或「退出」——重置选择状态。"""
    return {
        "chat_result": ChatResult(
            intent="chat",
            replyText="已取消选择，有什么其他需要帮忙的吗？",
        ),
        "interaction_mode": "normal",
        "pending_item_selection": None,
    }


def invalid_selection_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """【新增】用户输入了非有效序号——提示并保持选择状态。"""
    selection = state.get("pending_item_selection", [])
    return {
        "chat_result": ChatResult(
            intent="chat",
            replyText=f"请输入有效序号（1-{len(selection)}），或回复「取消」退出选择。",
        ),
        "interaction_mode": "item_select_confirm",
        "pending_item_selection": selection,
    }


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


def quantity_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """数量查询：按名称精准匹配物品，返回数量信息。"""
    import re as re_module
    text = state.get("text", "")
    inventory = state.get("inventory", [])
    search_terms = re_module.sub(r"[我你要看查还有剩几个多少在哪哪里]", "", text).strip()
    if not search_terms:
        search_terms = text

    # 精确匹配：按物品名称包含搜索词
    matches = [item for item in inventory if search_terms in item.title or item.title in search_terms]
    if not matches:
        matches = [item for item in inventory if any(term in item.title for term in search_terms.split() if term)]
    if not matches:
        matches = [item for item in inventory if search_terms in item.title or search_terms in item.spaceName or search_terms in item.location]
    if not matches:
        return {
            "chat_result": ChatResult(
                intent="quantity_query",
                replyText=f"我暂时没找到和「{search_terms}」相关的物品。",
            )
        }

    summary_parts = [f"{item.title}：{item.count}{item.unit}，位于{item.spaceName}/{item.location}" for item in matches[:6]]
    return {
        "chat_result": ChatResult(
            intent="quantity_query",
            replyText=f"当前查询到：{'；'.join(summary_parts)}。" if summary_parts else f"没找到「{search_terms}」相关物品。",
            itemSuggestion={"matches": [item.model_dump() for item in matches[:6]]},
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

    # === 新增节点 ===
    graph.add_node("confirm_selection", confirm_selection_node)
    graph.add_node("confirm_selection_all", confirm_selection_all_node)
    graph.add_node("reset_selection", reset_selection_node)
    graph.add_node("invalid_selection", invalid_selection_node)

    # 原有节点
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
    graph.add_node("quantity_query", quantity_query_node)
    graph.add_node("idle_query", idle_query_node)
    graph.add_node("recipe", recipe_node)
    graph.add_node("chat", chat_node)

    # === 优先路由：START → route_mode（比 classify_intent 优先级更高） ===
    graph.add_conditional_edges(
        START,
        route_mode,
        {
            "classify_intent": "classify_intent",
            "confirm_selection": "confirm_selection",
            "confirm_selection_all": "confirm_selection_all",
            "reset_selection": "reset_selection",
            "invalid_selection": "invalid_selection",
        },
    )

    # 意图路由（只有走到 classify_intent 才会触发）
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
            "quantity_query": "quantity_query",
            "search_query": "search_query",
            "idle_query": "idle_query",
            "recipe": "recipe",
            "chat": "chat",
        },
    )

    # 所有节点连接到 END
    for node in [
        "confirm_selection", "confirm_selection_all", "reset_selection", "invalid_selection",
        "add", "consume", "remove",
        "update_location", "update_expiry", "update_remaining",
        "expiry_query", "location_query", "quantity_query", "search_query", "idle_query",
        "recipe", "chat",
    ]:
        graph.add_edge(node, END)

    return graph.compile()


squirrel_graph = build_squirrel_graph()


def run_squirrel_graph(
    text: str,
    inventory: list[Item] | None = None,
    interaction_mode: str = "normal",
    pending_item_selection: list | None = None,
) -> SquirrelGraphState:
    """【重写】支持跨轮次选择状态传递。"""
    return squirrel_graph.invoke({
        "text": text,
        "inventory": inventory or [],
        "interaction_mode": interaction_mode,
        "pending_item_selection": pending_item_selection,
    })