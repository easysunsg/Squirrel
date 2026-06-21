import logging
from typing import TypedDict

from app.models.schemas import ChatOperation, ChatResult, Item, RecipeRequest
from app.services.cache import get_recipe_cache, set_recipe_cache
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
    recipe_recommend: dict
    user_preference: str
    reminder_time: str
    # === 跨轮次物品选择交互状态（持久化到 SQLite conversation_state 表） ===
    interaction_mode: str          # "normal" | "item_select_confirm"
    pending_item_selection: list   # [{"index":1,"id":"...","title":"...","location":"...","spaceName":"...","count":1,"unit":"个","remainingPct":100,"consumeAll":false}]
    pending_operation: dict | None # {"type":"update_location","patch":{"location":"冰箱上层"},"target":"牛奶"} 等待序号确认的操作
    last_added_item: dict | None   # 最近一次新增成功的物品（用于近指代）
    current_context_item: dict | None  # 当前对话上下文物品（用于省略句补全）


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
    last_added = state.get("last_added_item")
    current_context = state.get("current_context_item")

    # === 近指代优先处理 ===
    near_ref_match = _resolve_near_reference(text, last_added, inventory)
    if near_ref_match:
        return near_ref_match

    # Try LLM first
    if llm_service.enabled:
        try:
            inventory_summary = summarize_titles(inventory, limit=10) if inventory else "库存为空"
            llm_result = llm_service.classify_intent(text, inventory_summary)
            intent = llm_result.get("intent", "unknown")
            entities = llm_result.get("entities", {})

            if intent != "unknown":
                chat_result = ChatResult(intent=intent, replyText=f"已识别意图：{intent}")

                if intent == "add":
                    parsed_items = parse_lightning_text(text)
                    chat_result.operations = [ChatOperation(type="add", item=item) for item in parsed_items]
                    chat_result.replyText = f"已识别出 {len(parsed_items)} 件物品，准备入库。"
                elif intent == "consume" or intent == "remove":
                    target = entities.get("target")
                    # 上下文补全：无目标时依次尝试 current_context_item → last_added_item
                    if not target and current_context and current_context.get("title"):
                        target = current_context["title"]
                    if not target and last_added and last_added.get("title"):
                        if any(w in text for w in ["刚刚", "刚才", "刚"]):
                            target = last_added["title"]
                    # 数量提取：始终在 patch 中包含 count
                    patch = None
                    if intent == "consume":
                        remaining_pct = entities.get("remaining_pct")
                        count = entities.get("count")
                        if remaining_pct is not None or count is not None:
                            patch = {}
                            if remaining_pct is not None:
                                patch["remainingPct"] = remaining_pct
                            if count is not None:
                                patch["deductCount"] = count
                    if target:
                        chat_result.operations = [ChatOperation(type=intent, target=target, patch=patch)]
                    else:
                        chat_result.replyText = "请问你说的是哪个物品呢？可以告诉我物品名称。"
                        chat_result.operations = []
                elif intent == "update_location":
                    target = entities.get("target")
                    if not target and current_context and current_context.get("title"):
                        target = current_context["title"]
                    location = entities.get("location")
                    if target and location:
                        chat_result.operations = [ChatOperation(type="update", target=target, patch={"location": location})]
                    elif target and not location:
                        chat_result.replyText = "请问你想把物品放到哪里？"
                        chat_result.operations = []
                elif intent == "update_expiry":
                    target = entities.get("target")
                    if not target and current_context and current_context.get("title"):
                        target = current_context["title"]
                    expire_days = entities.get("expire_days")
                    if target and expire_days is not None:
                        from app.services.parser import days_from_now
                        chat_result.operations = [ChatOperation(type="update", target=target, patch={"expireDate": days_from_now(expire_days)})]

                logger.info("LLM intent classification succeeded intent=%s", intent)
                return {
                    "text": text,
                    "inventory": inventory,
                    "chat_result": chat_result,
                    "last_added_item": last_added,
                    "current_context_item": current_context,
                }
        except Exception:
            logger.exception("LLM intent classification failed, falling back to rules")

    # Fallback to rule-based
    return {
        "text": text,
        "inventory": inventory,
        "chat_result": build_chat_result(text),
        "last_added_item": last_added,
        "current_context_item": current_context,
    }


def _resolve_near_reference(text: str, last_added: dict | None, inventory: list[Item]) -> SquirrelGraphState | None:
    """近指代消解：检测「刚刚添加的/刚买的/刚才的」等表述，自动关联最近新增物品。"""
    if not last_added:
        return None
    import re as re_mod
    near_patterns = re_mod.findall(r"刚刚添加的|刚买的|刚才的|刚入库的|刚才添加的|刚刚的|刚加的|刚进的", text)
    if not near_patterns:
        return None

    last_title = last_added.get("title", "")
    if not last_title:
        return None

    # 检测意图：是否包含位置/保质期修改
    from app.services.parser import extract_location_update, extract_expire_patch
    location = extract_location_update(text)
    expire_patch = extract_expire_patch(text)

    # 精确匹配最近新增物品
    matched_item = next((it for it in inventory if it.id == last_added.get("id")), None)
    if not matched_item:
        matched_item = next((it for it in inventory if it.title == last_title), None)

    if not matched_item:
        return None

    if location:
        return {
            "text": text,
            "inventory": inventory,
            "chat_result": ChatResult(
                intent="update_location",
                replyText=f"已将「{matched_item.title}」的存放位置调整为：{location}，当前数量：{matched_item.count}{matched_item.unit}",
                operations=[],
                confirmedItemId=matched_item.id,
                confirmedPatch={"location": location},
            ),
        }

    if expire_patch:
        return {
            "text": text,
            "inventory": inventory,
            "chat_result": ChatResult(
                intent="update_expiry",
                replyText=f"已将「{matched_item.title}」的保质期更新。",
                operations=[],
                confirmedItemId=matched_item.id,
                confirmedPatch=expire_patch,
            ),
        }

    # 默认返回位置更新意图（如果有目标关键词）
    if any(w in text for w in ["放到", "放", "移到"]):
        after_pattern = text.split(near_patterns[-1])[-1].strip()
        possible_loc = after_pattern.replace("放到", "").replace("放在", "").replace("移到", "").strip()
        if possible_loc:
            return {
                "text": text,
                "inventory": inventory,
                "chat_result": ChatResult(
                    intent="update_location",
                    replyText=f"已将「{matched_item.title}」的存放位置调整为：{possible_loc}，当前数量：{matched_item.count}{matched_item.unit}",
                    operations=[],
                    confirmedItemId=matched_item.id,
                    confirmedPatch={"location": possible_loc},
                ),
            }

    return None


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

    # === 计算消耗数量（所有候选共用同一个 deduct 逻辑） ===
    def _calc_deduct(item: Item) -> int | None:
        if not operations or not operations[0].patch:
            return None
        patch = operations[0].patch
        llm_deduct = patch.get("deductCount")
        if llm_deduct is not None:
            return min(llm_deduct, item.count)
        patch_count = patch.get("count")
        patch_remaining_pct = patch.get("remainingPct")
        if patch_remaining_pct is not None and patch_remaining_pct == 0:
            return item.count
        elif patch_count is not None:
            return max(0, item.count - patch_count)
        return None

    # === 单候选：无需序号选择，直接执行 ===
    if len(candidates) == 1:
        item = candidates[0]
        deduct_count = _calc_deduct(item)
        unit_part = f"{item.count}{item.unit}" if item.count else ""
        ctx_item = _build_context_item(item)

        if deduct_count is not None and deduct_count > 0:
            if deduct_count >= item.count:
                reply_text = f"已消耗完「{item.title}」（{item.count}{item.unit}），已从库存移除。"
            else:
                new_count = item.count - deduct_count
                reply_text = f"已消耗 {deduct_count}{item.unit}「{item.title}」，剩余 {new_count}{item.unit}。"
            return {
                "chat_result": ChatResult(
                    intent="consume",
                    replyText=reply_text,
                    confirmedItemId=item.id,
                    confirmedDeductCount=deduct_count,
                    operations=[],
                ),
                "interaction_mode": "normal",
                "pending_item_selection": None,
                "current_context_item": ctx_item,
            }

        # 无明确数量 → 仍需确认
        return {
            "chat_result": ChatResult(
                intent="consume",
                replyText=f"找到「{item.title}」— {item.spaceName}/{item.location} ({unit_part}，剩余{item.remainingPct}%)，确认要操作吗？\n回复「1」确认，或输入其他内容取消。",
                needsConfirmation=True,
                operations=operations,
                itemSuggestion={"matches": [item.model_dump()], "consumeAll": consume_all},
            ),
            "interaction_mode": "item_select_confirm",
            "pending_item_selection": [{
                "id": item.id, "title": item.title, "spaceName": item.spaceName,
                "location": item.location, "count": item.count, "unit": item.unit,
                "remainingPct": item.remainingPct, "consumeAll": consume_all, "deductCount": None,
            }],
            "current_context_item": ctx_item,
        }

    # === 多候选：进入序号选择流程 ===
    candidates = candidates[:6]
    pending_selection = []
    for item in candidates:
        deduct_count = _calc_deduct(item)
        pending_selection.append({
            "id": item.id, "title": item.title, "spaceName": item.spaceName,
            "location": item.location, "count": item.count, "unit": item.unit,
            "remainingPct": item.remainingPct, "consumeAll": consume_all, "deductCount": deduct_count,
        })

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
    """用户回复数字序号——匹配 pending_item_selection，返回待执行的物品操作。

    根据 pending_operation 判断是消耗/删除还是属性修改，返回对应标志。
    """
    text = state.get("text", "").strip()
    selection = state.get("pending_item_selection", [])
    pending_op = state.get("pending_operation")

    index = int(text) - 1  # 用户输入从 1 开始
    if index < 0 or index >= len(selection):
        return {
            "chat_result": ChatResult(
                intent="chat",
                replyText=f"序号超出范围，请回复 1-{len(selection)} 之间的数字，或回复「取消」退出选择。",
            ),
            "interaction_mode": "item_select_confirm",
            "pending_item_selection": selection,
            "pending_operation": pending_op,
            "last_added_item": state.get("last_added_item"),
        }

    selected = selection[index]
    item_title = selected.get("title", "")
    item_id = selected.get("id")
    unit_part = f"{selected.get('count', 0)}{selected.get('unit', '个')}" if selected.get("count") else ""

    # 根据 pending_operation 判断操作类型
    if pending_op and pending_op.get("type", "").startswith("update_"):
        patch = pending_op.get("patch", {})
        op_type = pending_op.get("type", "update_location")

        if op_type == "update_location":
            loc = patch.get("location", "")
            reply_text = f"已将「{item_title}」的存放位置调整为：{selected.get('spaceName', '')}/{loc}，当前数量：{unit_part}"
        elif op_type == "update_expiry":
            reply_text = f"已更新「{item_title}」的保质期。"
        else:
            reply_text = f"已更新「{item_title}」。"

        return {
            "chat_result": ChatResult(
                intent=op_type,
                replyText=reply_text,
                operations=[],
                confirmedItemId=item_id,
                confirmedPatch=patch,
            ),
            "interaction_mode": "normal",
            "pending_item_selection": None,
            "pending_operation": None,
            "last_added_item": state.get("last_added_item"),
        }

    # 默认：消耗/删除流程
    consume_all = selected.get("consumeAll", False)
    deduct_count = selected.get("deductCount")

    chat_result = ChatResult(
        intent="consume",
        replyText=f"已确认选择：{item_title}。正在为你处理...",
        needsConfirmation=True,
        confirmedItemId=item_id,
        confirmedAllItems=consume_all,
    )
    if deduct_count is not None:
        chat_result.confirmedDeductCount = deduct_count

    return {
        "chat_result": chat_result,
        "interaction_mode": "normal",
        "pending_item_selection": None,
        "pending_operation": None,
        "last_added_item": state.get("last_added_item"),
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
    """位置更新节点——支持多候选选择与单候选直接执行。"""
    chat_result = state["chat_result"]
    operations = chat_result.operations
    inventory = state.get("inventory", [])
    if not operations:
        return {"chat_result": chat_result}

    op = operations[0]
    target = op.target
    patch = op.patch or {}
    candidates = _match_items_3tier(inventory, target)

    if not candidates:
        return {
            "chat_result": ChatResult(
                intent="update_location",
                replyText=f"没有找到「{target}」相关的物品，你可以先告诉我要新增的物品信息。",
            )
        }

    # 单候选：直接执行，通过 confirmedItemId + confirmedPatch
    if len(candidates) == 1:
        item = candidates[0]
        loc = patch.get("location", "")
        unit_part = f"{item.count}{item.unit}" if item.count else ""
        return {
            "chat_result": ChatResult(
                intent="update_location",
                replyText=f"已将「{item.title}」的存放位置调整为：{item.spaceName}/{loc}，当前数量：{unit_part}",
                operations=[],
                confirmedItemId=item.id,
                confirmedPatch=patch,
            )
        }

    # 多候选：进入选择流程
    candidates = candidates[:6]
    pending_selection = []
    for item in candidates:
        pending_selection.append({
            "id": item.id,
            "title": item.title,
            "spaceName": item.spaceName,
            "location": item.location,
            "count": item.count,
            "unit": item.unit,
            "remainingPct": item.remainingPct,
            "consumeAll": False,
        })

    lines = [f"找到 {len(candidates)} 个匹配物品，请回复序号选择要调整的物品："]
    for i, item in enumerate(candidates, 1):
        unit_part = f"{item.count}{item.unit}" if item.count else ""
        lines.append(f"{i}. {item.title} — {item.spaceName}/{item.location} ({unit_part})")

    return {
        "chat_result": ChatResult(
            intent="update_location",
            replyText="\n".join(lines),
            needsConfirmation=True,
            operations=[],
            itemSuggestion={"matches": [item.model_dump() for item in candidates]},
        ),
        "interaction_mode": "item_select_confirm",
        "pending_item_selection": pending_selection,
        "pending_operation": {"type": "update_location", "patch": patch, "target": target},
    }


def update_expiry_node(state: SquirrelGraphState) -> SquirrelGraphState:
    return {"chat_result": state["chat_result"]}


def update_remaining_node(state: SquirrelGraphState) -> SquirrelGraphState:
    return {"chat_result": state["chat_result"]}


def expiry_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    inventory = state.get("inventory", [])
    danger = [item for item in inventory if item_status(item) == "danger"]
    if not danger:
        return {"chat_result": ChatResult(intent="expiry_query", replyText="当前没有红色告急或过期预警物品。"), "current_context_item": None}
    summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in danger[:6])
    return {"chat_result": ChatResult(intent="expiry_query", replyText=f"现在最需要优先处理的是：{summary}。"), "current_context_item": None}


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
            ),
            "current_context_item": None,
        }
    item = candidates[0]
    ctx = _build_context_item(item) if len(candidates) == 1 else None
    return {
        "chat_result": ChatResult(
            intent="location_query",
            replyText=f"{item.title} 在 {item.spaceName} / {item.location}，当前剩余 {item.remainingPct}%。",
        ),
        "current_context_item": ctx,
    }


def _build_context_item(item: Item) -> dict:
    return {"id": item.id, "title": item.title, "location": item.location,
            "spaceName": item.spaceName, "count": item.count, "unit": item.unit}


def quantity_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """数量查询：按名称精准匹配物品，返回数量信息。"""
    import re as re_module
    text = state.get("text", "")
    inventory = state.get("inventory", [])
    search_terms = re_module.sub(r"[我你要看查还有剩几个多少在哪哪里]", "", text).strip()
    if not search_terms:
        search_terms = text

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
            ),
            "current_context_item": None,
        }

    summary_parts = [f"{item.title}：{item.count}{item.unit}，位于{item.spaceName}/{item.location}" for item in matches[:6]]
    # 查询后始终设置上下文（单条直接继承，多条取首条供后续省略句使用）
    ctx = _build_context_item(matches[0]) if matches else None
    return {
        "chat_result": ChatResult(
            intent="quantity_query",
            replyText=f"当前查询到：{'；'.join(summary_parts)}。",
            itemSuggestion={"matches": [item.model_dump() for item in matches[:6]]},
        ),
        "current_context_item": ctx,
    }


def search_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    text = state.get("text", "")
    inventory = state.get("inventory", [])
    matches = match_search_items(text, inventory)
    if not matches:
        return {"chat_result": ChatResult(intent="search_query", replyText="我暂时没搜到相关库存。"), "current_context_item": None}
    summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in matches[:6])
    ctx = _build_context_item(matches[0]) if len(matches) == 1 else None
    return {
        "chat_result": ChatResult(
            intent="search_query",
            replyText=f"我找到这些相关物品：{summary}。",
            itemSuggestion={"matches": [item.model_dump() for item in matches[:6]]},
        ),
        "current_context_item": ctx,
    }


def idle_query_node(state: SquirrelGraphState) -> SquirrelGraphState:
    inventory = state.get("inventory", [])
    idle = sorted(
        [item for item in inventory if item.remainingPct >= 80 and item_status(item) == "full"],
        key=lambda item: item.buyDate or "",
    )
    if not idle:
        return {"chat_result": ChatResult(intent="idle_query", replyText="当前没有明显长期闲置的物品。"), "current_context_item": None}
    summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in idle[:6])
    return {"chat_result": ChatResult(intent="idle_query", replyText=f"这些物品可能放了比较久：{summary}。"), "current_context_item": None}


def recipe_node(state: SquirrelGraphState) -> SquirrelGraphState:
    """Generate recipe using LLM with structured recipe recommendation.

    Collects expiring food items, sorts by urgency (expire_days ASC, quantity DESC),
    and generates a structured recipe recommendation.
    """
    inventory = state.get("inventory", [])

    # === Build expiring food list ===
    expiring_list = []
    for item in inventory:
        if item.category != "food":
            continue
        st = item_status(item)
        expire_days = _calc_expire_days(item)
        # Include items that are expired, warning, or fresh-but-close
        if st != "full" or (item.expireDate and expire_days is not None and expire_days <= 7):
            expiring_list.append({
                "name": item.title,
                "quantity": item.count,
                "unit": item.unit,
                "expire_days": expire_days or 0,
            })

    # Sort: expire_days ASC (most urgent first), quantity DESC (more left = higher priority)
    expiring_list.sort(key=lambda x: (x["expire_days"], -x["quantity"]))
    expiring_list = expiring_list[:10]  # cap at 10

    # Build user preference string from state if available
    pref = state.get("user_preference", "无特殊要求")
    reminder_time = state.get("reminder_time", "")

    # === Check cache (includes reminder_time in key) ===
    cached = get_recipe_cache(expiring_list, pref, reminder_time)
    if cached:
        return {
            "chat_result": ChatResult(
                intent="recipe",
                replyText=cached.get("recipe_recommend", {}).get("intro", "菜谱已生成"),
            ),
            "recipe_recommend": cached,
            "recipe": cached,
            "current_context_item": None,
        }

    # === Generate via LLM ===
    result = llm_service.generate_expiring_recipe(expiring_list, pref)

    # Cache successful (non-fallback) results with reminder_time in key
    if not result.get("isFallback") and result.get("recipe_recommend"):
        set_recipe_cache(expiring_list, pref, result, reminder_time)

    # === Build reply text ===
    if result.get("isFallback") and result.get("fallbackText"):
        reply = result["fallbackText"]
    elif result.get("recipe_recommend"):
        rec = result["recipe_recommend"]
        reply = rec.get("intro", "菜谱已生成")
    else:
        reply = "暂无足够的食材信息生成菜谱，请先添加一些食材到库存吧。"

    return {
        "chat_result": ChatResult(intent="recipe", replyText=reply),
        "recipe_recommend": result,
        "recipe": result,
        "current_context_item": None,
    }


def _calc_expire_days(item: Item) -> int | None:
    """Calculate remaining days until expiry. Negative means expired."""
    if not item.expireDate:
        return None
    from datetime import date, datetime
    try:
        expiry = datetime.strptime(item.expireDate, "%Y-%m-%d").date()
        delta = (expiry - date.today()).days
        return delta
    except (ValueError, TypeError):
        return None


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
                "chat_result": ChatResult(intent="chat", replyText=reply),
                "current_context_item": None,
            }
        except Exception:
            logger.exception("LLM chat reply failed, falling back to template")

    # Fallback to template
    return {
        "chat_result": ChatResult(
            intent="chat",
            replyText=f"我查到当前共有 {len(inventory)} 件库存。你可以让我录入、查位置、列临期或生成菜谱。",
        ),
        "current_context_item": None,
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
    pending_operation: dict | None = None,
    last_added_item: dict | None = None,
    current_context_item: dict | None = None,
    user_preference: str = "无特殊要求",
    reminder_time: str = "",
) -> SquirrelGraphState:
    """支持跨轮次选择状态传递。"""
    return squirrel_graph.invoke({
        "text": text,
        "inventory": inventory or [],
        "interaction_mode": interaction_mode,
        "pending_item_selection": pending_item_selection,
        "pending_operation": pending_operation,
        "last_added_item": last_added_item,
        "current_context_item": current_context_item,
        "user_preference": user_preference,
        "reminder_time": reminder_time,
    })