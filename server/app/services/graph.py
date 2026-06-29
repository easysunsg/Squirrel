"""新架构 LangGraph — 6 节点简洁拓扑

重写说明：
- 保留 run_squirrel_graph 签名不变，外部使用者（ai.py / test_graph.py）无需改动
- 内部使用 ExtendedGraphState 流转，输出前通过 extended_to_old_dict 适配回旧格式
- 所有路径收敛到 post_process，消灭直通 END 的叶子节点
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from app.models.schemas import ChatOperation, ChatResult, Item, RecipeRequest
from app.models.state import (
    ExtendedGraphState,
    PendingOperation,
    UserContext,
    merge_audit_logs,
)
from app.services.cache import get_recipe_cache, set_recipe_cache
from app.services.llm import llm_service
from app.services.markdown import item_status
from app.services.parser import (
    build_chat_result,
    days_from_now,
    extract_expire_patch,
    extract_location_update,
    extract_remaining_patch,
    extract_search_keyword,
    infer_search_terms,
    parse_lightning_text,
    parse_multi_selection,
)
from app.services.spatial_service import spatial_service
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)

# ==============================
# 共享工具函数（移植自旧图）
# ==============================


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


def _match_items_3tier(inventory: list[Item], target: str | None) -> list[Item]:
    """3-tier matching: exact → substring → spatial path → location/space fallback."""
    if not target:
        return []
    exact = [item for item in inventory if item.title == target]
    if exact:
        return exact
    partial = [item for item in inventory if target in item.title or item.title in target]
    if partial:
        return partial
    slot_ids = spatial_service.resolve_location_to_slots(target)
    if slot_ids:
        results = [item for item in inventory if item.belongsToSlotId in slot_ids]
        if results:
            return results
    return [item for item in inventory if target in item.location or target in item.spaceName]


def _build_candidate_entries(candidates: list[Item]) -> list[dict]:
    entries = []
    for item in candidates:
        entries.append({
            "id": item.id, "title": item.title, "spaceName": item.spaceName,
            "location": item.location, "count": item.count, "unit": item.unit,
            "remainingPct": item.remainingPct, "consumeAll": False,
            "expire_date": item.expireDate or "",
            "expire_days": _calc_expire_days(item),
        })
    return entries


def _build_candidate_lines(candidates: list[Item], target: str | None = None) -> list[str]:
    noun = target or "物品"
    lines = [f"找到 {len(candidates)} 个匹配的「{noun}」，请回复序号选择（支持多选，如「1,2」「全部」）："]
    for i, item in enumerate(candidates, 1):
        unit_part = f"{item.count}{item.unit}" if item.count else ""
        days = _calc_expire_days(item)
        if days is not None:
            expire_str = f"{item.expireDate}到期（剩余{days}天"
            if days <= 3:
                expire_str += " ⚠️即将过期"
            expire_str += "）"
        else:
            expire_str = "无过期信息"
        lines.append(f"{i}. {item.title} — {item.spaceName}/{item.location} ({unit_part}，{expire_str})")
    return lines


def _build_context_item(item: Item) -> dict:
    return {"id": item.id, "title": item.title, "location": item.location,
            "spaceName": item.spaceName, "count": item.count, "unit": item.unit}


def _calc_expire_days(item: Item) -> int | None:
    if not item.expireDate:
        return None
    try:
        expiry = datetime.strptime(item.expireDate, "%Y-%m-%d").date()
        delta = (expiry - date.today()).days
        return delta
    except (ValueError, TypeError):
        return None


def _build_multi_consume_allocation(selected_items: list[dict], total_deduct: int | None) -> dict[str, int]:
    sorted_items = sorted(
        selected_items,
        key=lambda item: (
            item.get("expire_days") if item.get("expire_days") is not None else 9999,
            -item.get("count", 0),
        ),
    )
    allocation: dict[str, int] = {}
    remaining = total_deduct
    for item in sorted_items:
        item_id = item.get("id")
        count = item.get("count", 0)
        if not item_id:
            continue
        if remaining is not None:
            deduct = min(remaining, count)
            remaining -= deduct
            if deduct > 0:
                allocation[item_id] = deduct
        else:
            if count > 0:
                allocation[item_id] = 1
    return allocation


def _build_multi_consume_reply(selected_items: list[dict], allocation: dict[str, int]) -> str:
    parts = []
    total_deducted = 0
    unit_str = "个"
    for item in selected_items:
        item_id = item.get("id")
        title = item.get("title", "?")
        count = item.get("count", 0)
        unit = item.get("unit", "个")
        location = item.get("location", "?")
        space = item.get("spaceName", "")
        deduct = allocation.get(item_id, 0)
        unit_str = unit
        if deduct > 0:
            total_deducted += deduct
            if deduct >= count:
                parts.append(f"{space}/{location}的「{title}」：消耗{deduct}{unit}，已用完")
            else:
                new_count = count - deduct
                parts.append(f"{space}/{location}的「{title}」：消耗{deduct}{unit}，剩余{new_count}{unit}")
        else:
            parts.append(f"{space}/{location}的「{title}」：未操作（剩余{count}{unit}）")
    if total_deducted > 0:
        parts.append(f"总共消耗{total_deducted}{unit_str}")
    return "\n".join(parts)


def _build_multi_remove_reply(selected_items: list[dict]) -> str:
    locations = []
    for item in selected_items:
        loc = item.get("location", "?")
        space = item.get("spaceName", "")
        title = item.get("title", "?")
        locations.append(f"{space}/{loc}的「{title}」")
    return f"已移除 {len(selected_items)} 个位置的物品：{'、'.join(locations)}"


def _build_multi_update_reply(selected_items: list[dict], op_type: str, patch: dict) -> str:
    titles = [item.get("title", "?") for item in selected_items]
    if op_type == "update_location":
        loc = patch.get("location", "")
        return f"已将 {len(selected_items)} 件物品移动到{loc}：{'、'.join(titles)}"
    return f"已更新 {len(selected_items)} 件物品：{'、'.join(titles)}"


# ==============================
# 节点 1: Multimodal & Identity Router
# ==============================

_ESCAPE_WORDS = ["取消", "算了", "不要了", "exit", "quit", "返回"]


def multimodal_identity_router_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【入口节点】输入清洗、escape 词检测、mutation_logs 初始化。"""
    raw_text = state.get("raw_text_input", "").strip()
    current_user = state.get("current_user")
    current_mode = state.get("interaction_mode", "normal")
    user_name = current_user.user_name if current_user else "主人"

    logger.info("[Input Router] 来自用户(%s)的输入. 模式: %s", user_name, current_mode)

    state_updates: Dict[str, Any] = {}

    # 强中断机制：pending 状态下用户输入 escape 词
    if current_mode == "pending_selection" and raw_text in _ESCAPE_WORDS:
        logger.info("[Input Router] 检测到强中断，重置为 normal 模式")
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "reply_text": f"好滴{user_name}，已经帮您取消了刚才的操作。咱们重新开始，您想处理点什么物资？",
        }

    # 补全 mutation_logs
    if "mutation_logs" not in state or state["mutation_logs"] is None:
        state_updates["mutation_logs"] = []

    return state_updates


def route_after_input(state: ExtendedGraphState) -> Literal["go_to_confirm_handler", "go_to_intent_classifier", "end_early"]:
    """【条件路由】pending → confirm_handler / normal → intent_classifier / escape → end_early。"""
    reply_text = state.get("reply_text", "")
    # escape 已触发，直接出图
    if reply_text and "已经帮您取消了刚才的操作" in reply_text:
        return "end_early"
    if state.get("interaction_mode") == "pending_selection":
        logger.info("[Input Router] 有事务挂起 -> 流向 Confirm Handler")
        return "go_to_confirm_handler"
    logger.info("[Input Router] 正常新输入 -> 流向 Intent Classifier")
    return "go_to_intent_classifier"


# ==============================
# 节点 2: Intent Classifier
# ==============================

def _resolve_near_reference(
    text: str, last_added: dict | None, inventory: list[Item],
) -> Dict[str, Any] | None:
    """近指代消解：检测「刚刚添加的/刚买的」等表述，自动关联最近新增物品。"""
    if not last_added:
        return None
    import re as re_mod
    near_patterns = re_mod.findall(r"刚刚添加的|刚买的|刚才的|刚入库的|刚才添加的|刚刚的|刚加的|刚进的", text)
    if not near_patterns:
        return None
    last_title = last_added.get("title", "")
    if not last_title:
        return None
    location = extract_location_update(text)
    expire_patch = extract_expire_patch(text)
    matched_item = next((it for it in inventory if it.id == last_added.get("id")), None)
    if not matched_item:
        matched_item = next((it for it in inventory if it.title == last_title), None)
    if not matched_item:
        return None
    if location:
        return {
            "intent": "update_location",
            "reply_text": f"已将「{matched_item.title}」的存放位置调整为：{location}，当前数量：{matched_item.count}{matched_item.unit}",
            "extracted_entities": {"target": matched_item.title, "location": location},
            "confirmed_item_id": matched_item.id,
            "confirmed_patch": {"location": location},
        }
    if expire_patch:
        return {
            "intent": "update_expiry",
            "reply_text": f"已将「{matched_item.title}」的保质期更新。",
            "extracted_entities": {"target": matched_item.title},
            "confirmed_item_id": matched_item.id,
            "confirmed_patch": expire_patch,
        }
    if any(w in text for w in ["放到", "放", "移到"]):
        after_pattern = text.split(near_patterns[-1])[-1].strip()
        possible_loc = after_pattern.replace("放到", "").replace("放在", "").replace("移到", "").strip()
        if possible_loc:
            return {
                "intent": "update_location",
                "reply_text": f"已将「{matched_item.title}」的存放位置调整为：{possible_loc}，当前数量：{matched_item.count}{matched_item.unit}",
                "extracted_entities": {"target": matched_item.title, "location": possible_loc},
                "confirmed_item_id": matched_item.id,
                "confirmed_patch": {"location": possible_loc},
            }
    return None


def intent_classifier_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【意图分类】LLM 分类 + rule fallback + 近指代消解。"""
    text = state.get("raw_text_input", "")
    inventory = state.get("inventory", [])
    last_added = state.get("last_added_item")
    current_context = state.get("current_context_item")

    # 近指代优先
    near_ref = _resolve_near_reference(text, last_added, inventory)
    if near_ref:
        return near_ref

    # LLM 分类
    chat_result = None
    if llm_service.enabled:
        try:
            inventory_summary = summarize_titles(inventory, limit=10) if inventory else "库存为空"
            llm_result = llm_service.classify_intent(text, inventory_summary)
            intent = llm_result.get("intent", "unknown")
            entities = llm_result.get("entities", {})

            if intent != "unknown":
                reply_text = f"已识别意图：{intent}"
                extracted: Dict[str, Any] = {}

                if intent == "add":
                    parsed_items = parse_lightning_text(text)
                    reply_text = f"已识别出 {len(parsed_items)} 件物品，准备入库。"
                    extracted["items"] = [item.model_dump() for item in parsed_items]
                    extracted["item_count"] = len(parsed_items)

                elif intent in ("consume", "remove"):
                    target = entities.get("target")
                    if not target and current_context and current_context.get("title"):
                        target = current_context["title"]
                    if not target and last_added and last_added.get("title"):
                        if any(w in text for w in ["刚刚", "刚才", "刚"]):
                            target = last_added["title"]
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
                        extracted["target"] = target
                        extracted["patch"] = patch
                    else:
                        reply_text = "请问你说的是哪个物品呢？可以告诉我物品名称。"

                elif intent == "update_location":
                    target = entities.get("target")
                    if not target and current_context and current_context.get("title"):
                        target = current_context["title"]
                    location = entities.get("location")
                    if target and location:
                        extracted["target"] = target
                        extracted["patch"] = {"location": location}
                    elif target and not location:
                        reply_text = "请问你想把物品放到哪里？"

                elif intent == "update_expiry":
                    target = entities.get("target")
                    if not target and current_context and current_context.get("title"):
                        target = current_context["title"]
                    expire_days = entities.get("expire_days")
                    if target and expire_days is not None:
                        extracted["target"] = target
                        extracted["patch"] = {"expireDate": days_from_now(expire_days)}

                elif intent in ("quantity_query", "location_query", "search_query", "recipe"):
                    # 将大模型识别到的 target 或 keyword 保留下来
                    extracted["target"] = entities.get("target") or entities.get("keyword")

                logger.info("LLM intent classification succeeded intent=%s", intent)
                return {
                    "intent": intent,
                    "reply_text": reply_text,
                    "extracted_entities": extracted,
                    "last_added_item": last_added,
                    "current_context_item": current_context,
                }
        except Exception:
            logger.exception("LLM classification failed, falling back to rules")

    # Rule-based fallback
    fallback = build_chat_result(text)
    intent = fallback.intent
    entities: Dict[str, Any] = {}
    if fallback.operations:
        op = fallback.operations[0]
        entities["target"] = op.target
        entities["items"] = [op.item.model_dump()] if op.item else []
        if op.patch:
            entities["patch"] = op.patch
    return {
        "intent": intent,
        "reply_text": fallback.replyText,
        "extracted_entities": entities,
        "last_added_item": last_added,
        "current_context_item": current_context,
    }


def route_by_new_intent(state: ExtendedGraphState) -> Literal["mutation", "query"]:
    """【条件路由】mutation → conflict_batch_resolver / query → query_handler。"""
    intent = state.get("intent", "chat")
    if intent in ("add", "consume", "remove", "update_location", "update_expiry", "update_remaining"):
        return "mutation"
    return "query"


# ==============================
# 节点 3: Conflict & Batch Resolver
# ==============================

def conflict_batch_resolver_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【核心大脑】FIFO 批次锁定、多义性识别、防囤货拦截。"""
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    inventory = state.get("inventory", [])
    current_user = state.get("current_user")
    user_name = current_user.user_name if current_user else "主人"

    target_name = entities.get("target")
    if not target_name:
        # 从 add 的 items 中提取
        items_data = entities.get("items", [])
        if items_data:
            first = items_data[0] if isinstance(items_data[0], dict) else {}
            target_name = first.get("title", "")
        if not target_name:
            return {"reply_text": "管家听到您想操作物资，但没听清具体的物品名字，能再说一遍吗？"}

    candidates = _match_items_3tier(inventory, target_name)
    req_count = float(entities.get("patch", {}).get("deductCount", 1.0))

    if intent in ("consume", "remove") and not candidates:
        return {
            "interaction_mode": "normal",
            "reply_text": f"查了一下库存，咱们家现在好像没有「{target_name}」呢，是不是记错名字啦？",
        }

    # ----- ADD 意图 -----
    if intent == "add":
        items_data = entities.get("items", [])
        # 创建 PendingOperation 供 mutation_executor 使用
        add_count = float(entities.get("item_count", 1))
        pending_op = PendingOperation(
            type="add",
            target_sku_title=target_name,
            patch={"count": add_count, "items_data": items_data},
        )
        return {
            "pending_operation": pending_op,
            "reply_text": state.get("reply_text", ""),
        }

    # ----- CONSUME / REMOVE 意图 -----
    if intent in ("consume", "remove"):
        # 多义性消解
        if len(candidates) > 1:
            # 按临期升序 + 数量降序排序
            candidates.sort(key=lambda it: (_calc_expire_days(it) if _calc_expire_days(it) is not None else 9999, -it.count))
            candidates = candidates[:6]
            selection = _build_candidate_entries(candidates)
            lines = _build_candidate_lines(candidates, target_name)

            ded_patch = entities.get("patch") or {}
            pending_op = PendingOperation(
                type=intent,
                target_sku_title=target_name,
                patch=ded_patch,
            )
            return {
                "interaction_mode": "pending_selection",
                "pending_item_selection": selection,
                "pending_operation": pending_op,
                "reply_text": "\n".join(lines),
                "current_context_item": None,
            }

        # 单候选：FIFO 锁定
        target_item = candidates[0]
        ded_patch = entities.get("patch") or {}
        pending_op = PendingOperation(
            type=intent,
            target_sku_title=target_item.title,
            patch=ded_patch,
            source_batch_ids=[target_item.id] if target_item.id else [],
        )
        ctx_item = _build_context_item(target_item)
        logger.info("[Resolver] FIFO 锁定单品: %s", target_item.id)

        return {
            "pending_operation": pending_op,
            "current_context_item": ctx_item,
            "reply_text": f"找到「{target_item.title}」— {target_item.spaceName}/{target_item.location} ({target_item.count}{target_item.unit})，确认要操作吗？",
        }

    # ----- UPDATE 意图 -----
    if intent in ("update_location", "update_expiry", "update_remaining"):
        patch = entities.get("patch", {})
        if not candidates:
            return {"reply_text": f"没有找到「{target_name}」相关的物品。"}
        if len(candidates) > 1:
            candidates = candidates[:6]
            selection = _build_candidate_entries(candidates)
            lines = _build_candidate_lines(candidates, target_name)
            pending_op = PendingOperation(
                type=intent,
                target_sku_title=target_name,
                patch=patch,
            )
            return {
                "interaction_mode": "pending_selection",
                "pending_item_selection": selection,
                "pending_operation": pending_op,
                "reply_text": "\n".join(lines),
            }
        # 单候选直接确认
        item = candidates[0]
        return {
            "confirmed_item_id": item.id,
            "confirmed_patch": patch,
            "reply_text": f"已更新「{item.title}」。",
            "current_context_item": _build_context_item(item),
        }

    return {}


def route_after_resolver(state: ExtendedGraphState) -> Literal["execute", "pending"]:
    """【条件路由】clean → mutation_executor / pending → post_process。"""
    mode = state.get("interaction_mode", "normal")
    if mode == "pending_selection":
        return "pending"
    return "execute"


# ==============================
# 节点 4: Pending Confirmation Handler
# ==============================

def confirm_subgraph_handler_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【确认处理器】处理用户对候选列表的确认/取消/多选等。"""
    text = state.get("raw_text_input", "").strip()
    selection = state.get("pending_item_selection", [])
    pending_op = state.get("pending_operation")
    inventory = state.get("inventory", [])

    if not text:
        return {
            "interaction_mode": "pending_selection",
            "reply_text": f"请输入序号（1-{len(selection)}）或回复「取消」退出。",
        }

    # 取消
    if text in ("取消", "退出", "不选了", "算了"):
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "reply_text": "已取消选择，有什么其他需要帮忙的吗？",
        }

    # 全部选择
    if text in ("全部", "所有", "全选"):
        if not selection:
            return {"reply_text": "没有可清除的物品。", "interaction_mode": "normal"}
        # 生成 mutation_logs 式的全部清除
        item_ids = [s.get("id") for s in selection if s.get("id")]
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "confirmed_item_ids": item_ids,
            "reply_text": f"已清除所有匹配物品。",
        }

    # 解析序号
    parsed = parse_multi_selection(text, len(selection))
    if not isinstance(parsed, list) or len(parsed) == 0:
        return {
            "interaction_mode": "pending_selection",
            "reply_text": f"请输入有效序号（1-{len(selection)}），或回复「取消」退出。",
            "pending_item_selection": selection,
            "pending_operation": pending_op,
        }

    valid_indices = [i for i in parsed if 0 <= i < len(selection)]
    if not valid_indices:
        return {
            "interaction_mode": "pending_selection",
            "reply_text": f"序号超出范围，请输入 1~{len(selection)} 之间的数字。",
            "pending_item_selection": selection,
            "pending_operation": pending_op,
        }

    selected_items = [selection[i] for i in valid_indices]
    op_type = pending_op.type if pending_op else "consume"

    # --- 单选 ---
    if len(valid_indices) == 1 and text.isdigit() and 1 <= int(text) <= len(selection):
        sel = selected_items[0]
        item_id = sel.get("id")
        if op_type.startswith("update_"):
            patch = pending_op.patch if pending_op else {}
            return {
                "interaction_mode": "normal",
                "pending_item_selection": [],
                "pending_operation": None,
                "confirmed_item_id": item_id,
                "confirmed_patch": patch,
                "reply_text": f"已确认选择。",
            }
        # consume/remove 单选
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": PendingOperation(
                type=op_type,
                target_sku_title=sel.get("title", ""),
                patch=(pending_op.patch if pending_op else {}),
                source_batch_ids=[item_id] if item_id else [],
            ),
            "reply_text": f"已确认选择：{sel.get('title', '')}。正在为您处理...",
        }

    # --- 多选 ---
    item_ids = [s.get("id") for s in selected_items if s.get("id")]

    if op_type.startswith("update_"):
        patch = pending_op.patch if pending_op else {}
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "confirmed_item_ids": item_ids,
            "confirmed_patch": patch,
            "reply_text": _build_multi_update_reply(selected_items, op_type, patch),
        }

    if op_type == "remove":
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "confirmed_item_ids": item_ids,
            "reply_text": _build_multi_remove_reply(selected_items),
        }

    # 默认：consume 多选
    total_deduct = (pending_op.patch or {}).get("deductCount") if pending_op else None
    allocation = _build_multi_consume_allocation(selected_items, total_deduct)
    reply_text = _build_multi_consume_reply(selected_items, allocation)

    return {
        "interaction_mode": "normal",
        "pending_item_selection": [],
        "pending_operation": PendingOperation(
            type="consume",
            target_sku_title="",
            patch={"deductCounts": allocation},
            source_batch_ids=list(allocation.keys()),
        ),
        "reply_text": reply_text,
    }


def route_after_confirm(state: ExtendedGraphState) -> Literal["success", "cancel"]:
    """【条件路由】确认成功 → mutation_executor / 取消 → post_process。"""
    mode = state.get("interaction_mode", "normal")
    if mode == "pending_selection":
        return "cancel"  # 保持在 pending_selection -> post_process 刷新状态
    return "success"


# ==============================
# 节点 5: Mutation Executor
# ==============================

def mutation_executor_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【原子事务执行】生成 mutation_logs（不写 DB）。"""
    pending_op = state.get("pending_operation")
    current_user = state.get("current_user")
    inventory = state.get("inventory", [])
    confirmed_item_id = state.get("confirmed_item_id")
    confirmed_item_ids = state.get("confirmed_item_ids", [])
    confirmed_patch = state.get("confirmed_patch")
    user_id = current_user.user_id if current_user else "default"
    user_name = current_user.user_name if current_user else "主人"

    new_logs: List[Dict[str, Any]] = []
    reply_text = state.get("reply_text", "")
    pending_add_items: List[Dict[str, Any]] = []  # 用于返回给 adapter 层
    # --- 处理来自 confirm_handler 的单选 ID ---
    if confirmed_item_id and confirmed_patch:
        # update 操作：通过 patch 直接修改
        target = next((it for it in inventory if it.id == confirmed_item_id), None)
        if target:
            new_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": "update",
                "target_instance_id": confirmed_item_id,
                "sku_title": target.title,
                "patch": confirmed_patch,
                "delta": 0,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })
        return {
            "mutation_logs": new_logs,
            "interaction_mode": "normal",
            "pending_operation": None,
            "pending_item_selection": [],
        }

    if confirmed_item_ids:
        # 批量操作（移除/清除）
        for item_id in confirmed_item_ids:
            target = next((it for it in inventory if it.id == item_id), None)
            if confirmed_patch:
                new_logs.append({
                    "event_id": f"evt_{datetime.now().timestamp()}",
                    "op_type": "update",
                    "target_instance_id": item_id,
                    "sku_title": target.title if target else "",
                    "patch": confirmed_patch,
                    "delta": 0,
                    "operator_id": user_id,
                    "operator_name": user_name,
                    "timestamp": datetime.now().isoformat(),
                })
            else:
                new_logs.append({
                    "event_id": f"evt_{datetime.now().timestamp()}",
                    "op_type": "remove",
                    "target_instance_id": item_id,
                    "sku_title": target.title if target else "",
                    "delta": -(target.count if target else 1),
                    "operator_id": user_id,
                    "operator_name": user_name,
                    "timestamp": datetime.now().isoformat(),
                })
        return {
            "mutation_logs": new_logs,
            "interaction_mode": "normal",
            "pending_operation": None,
            "pending_item_selection": [],
        }

    # --- 处理 pending_operation ---
    if not pending_op:
        logger.warning("[Executor] 没有待执行的挂起事务")
        return {}

    logger.info("[Executor] 处理挂起事务: %s -> %s", pending_op.type, pending_op.target_sku_title)

    if pending_op.type == "add":
        add_count = pending_op.patch.get("count", 1.0)
        items_data = pending_op.patch.get("items_data", [])
        for item_dict in items_data:
            new_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": "add",
                "target_instance_id": f"new_{uuid4().hex[:12]}",
                "sku_title": item_dict.get("title", pending_op.target_sku_title),
                "delta": item_dict.get("count", add_count),
                "item_data": item_dict,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })
        if not reply_text:
            reply_text = f"登记成功！已帮您将物品录入系统。"

        # 🚨 修复：不直接修改 state，而是将增量数据放入返回字典，让 LangGraph 统一调度更新
        pending_add_items = items_data

    elif pending_op.type in ("consume", "remove"):
        deduct_count = pending_op.patch.get("deductCount", 1.0)

        # 支持多选分摊模式（deductCounts）
        deduct_counts = pending_op.patch.get("deductCounts", {})
        for batch_id in pending_op.source_batch_ids:
            target = next((it for it in inventory if it.id == batch_id), None)
            actual_deduct = 1
            if deduct_counts and isinstance(deduct_counts, dict):
                actual_deduct = deduct_counts.get(batch_id, 1)
            elif isinstance(deduct_count, (int, float)):
                actual_deduct = int(deduct_count)
            new_logs.append({
                "event_id": f"evt_{datetime.now().timestamp()}",
                "op_type": pending_op.type,
                "target_instance_id": batch_id,
                "sku_title": pending_op.target_sku_title,
                "delta": -actual_deduct,
                "operator_id": user_id,
                "operator_name": user_name,
                "timestamp": datetime.now().isoformat(),
            })

        if not reply_text:
            reply_text = f"好滴{user_name}，已帮您处理了 **{pending_op.target_sku_title}**。"

    return {
        "mutation_logs": new_logs,
        "interaction_mode": "normal",
        "pending_operation": None,
        "pending_item_selection": [],
        "reply_text": reply_text,
        "pending_add_items": pending_add_items,
    }


# ==============================
# 节点 6: Query & Recipe Handler
# ==============================

def query_handler_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【查询与菜谱】处理所有只读请求，使用 current_context_item 继承时空记忆。"""
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    inventory = state.get("inventory", [])
    current_context = state.get("current_context_item")
    user_pref = state.get("user_preference", "无特殊要求")
    reminder_time = state.get("reminder_time", "")

    # 跨轮次记忆回溯
    target_item_title = entities.get("target")
    target_location = "指定位置"
    if not target_item_title and current_context:
        target_item_title = current_context.get("title")
        target_location = current_context.get("location", "现有储物区")
        logger.info("[Query/Recipe] 触发上下文继承: title=%s location=%s", target_item_title, target_location)

    # ------ expiry_query ------
    if intent == "expiry_query":
        danger = [item for item in inventory if item_status(item) == "danger"]
        if not danger:
            return {"reply_text": "当前没有红色告急或过期预警物品。"}
        summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in danger[:6])
        return {"reply_text": f"现在最需要优先处理的是：{summary}。"}

    # ------ location_query ------
    if intent == "location_query":
        text = state.get("raw_text_input", "")
        candidates = [
            item for item in inventory
            if item.title in text or text in item.title or item.location in text or item.spaceName in text
        ]
        if not candidates:
            return {"reply_text": "我暂时没在库存里精确匹配到位置，可以试试输入更具体的物品名。"}
        item = candidates[0]
        ctx = _build_context_item(item) if len(candidates) == 1 else None
        return {
            "reply_text": f"{item.title} 在 {item.spaceName} / {item.location}，当前剩余 {item.remainingPct}%。",
            "current_context_item": ctx,
        }

    # ------ quantity_query ------
    if intent == "quantity_query":
        # 1. 优先从上游大模型提取的实体里拿
        query = entities.get("target")

        # 2. 如果上游没拿到，尝试从跨轮上下文记忆里继承
        if not query and current_context:
            query = current_context.get("title")

        # 3. 如果还是没有，才用正则 parser 兜底
        if not query:
            text = state.get("raw_text_input", "")
            from app.services.parser import extract_search_keyword
            query = extract_search_keyword(text)

        logger.info("[Query Handler] 数量查询关键词锁定为: %s", query)

        candidates = _match_items_3tier(inventory, query)
        if not candidates:
            return {"reply_text": f"没有找到「{query or '指定物品'}」相关信息。"}
        item = candidates[0]
        return {
            "reply_text": f"「{item.title}」还剩 {item.count}{item.unit}，在 {item.spaceName}{item.location}。",
            "current_context_item": _build_context_item(item),
        }

    # ------ search_query ------
    if intent == "search_query":
        text = state.get("raw_text_input", "")
        results = match_search_items(text, inventory)
        if not results:
            return {"reply_text": "没有找到匹配的物品。"}
        summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in results[:6])
        return {"reply_text": f"搜索到以下物品：{summary}。"}

    # ------ idle_query ------
    if intent == "idle_query":
        idle = [
            item for item in inventory
            if item.remainingPct >= 80 and item_status(item) == "full"
        ]
        idle.sort(key=lambda it: (it.buyDate or ""))
        if not idle:
            return {"reply_text": "当前没有明显长期闲置的物品。"}
        summary = "、".join(f"{item.title}（{item.spaceName}/{item.location}）" for item in idle[:6])
        return {"reply_text": f"这些物品可能放了比较久：{summary}。"}

    # ------ recipe ------
    if intent == "recipe":
        if not target_item_title:
            return {"reply_text": "您是想用哪些快过期的食材来生成菜单呢？可以随手拍张照片或者直接告诉管家哦。"}

        expiring_list = []
        for item in inventory:
            if item.category != "food":
                continue
            st = item_status(item)
            expire_days = _calc_expire_days(item)
            if st != "full" or (item.expireDate and expire_days is not None and expire_days <= 7):
                expiring_list.append({
                    "name": item.title,
                    "quantity": item.count,
                    "unit": item.unit,
                    "expire_days": expire_days or 0,
                })
        expiring_list.sort(key=lambda x: (x["expire_days"], -x["quantity"]))
        expiring_list = expiring_list[:10]

        cached = get_recipe_cache(expiring_list, user_pref, reminder_time)
        if cached:
            return {
                "reply_text": cached.get("recipe_recommend", {}).get("intro", "菜谱已生成"),
                "recipe_recommendation": cached,
            }

        result = llm_service.generate_expiring_recipe(expiring_list, user_pref)
        if not result.get("isFallback") and result.get("recipe_recommend"):
            set_recipe_cache(expiring_list, user_pref, result, reminder_time)

        if result.get("isFallback") and result.get("fallbackText"):
            reply = result["fallbackText"]
        elif result.get("recipe_recommend"):
            reply = result["recipe_recommend"].get("intro", "菜谱已生成")
        else:
            reply = "暂无足够的食材信息生成菜谱，请先添加一些食材到库存吧。"

        return {
            "reply_text": reply,
            "recipe_recommendation": result,
        }

    # ------ chat ------
    if intent == "chat":
        context_parts = [f"库存总数：{len(inventory)} 件"]
        danger = [item for item in inventory if item_status(item) == "danger"]
        if danger:
            context_parts.append(f"临期/告急：{len(danger)} 件")
        context = "；".join(context_parts)
        if llm_service.enabled:
            try:
                reply = llm_service.chat_reply(state.get("raw_text_input", ""), context)
                return {"reply_text": reply}
            except Exception:
                logger.exception("LLM chat failed, falling back")
        return {"reply_text": f"我查到当前共有 {len(inventory)} 件库存。你可以让我录入、查位置、列临期或生成菜谱。"}

    return {"reply_text": "收到，管家已为您处理完毕。"}


# ==============================
# 节点 7: Central Post Process
# ==============================

def post_process_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【统一出口】收敛 mutation_logs、保持上下文、日志记录。"""
    accumulated_logs = state.get("mutation_logs", [])
    current_context = state.get("current_context_item")
    reply_text = state.get("reply_text", "收到，管家已为您处理完毕。")

    logger.info("[Post Process] 本次流转产生 mutation_logs: %d 条", len(accumulated_logs))

    # 上下文防御：如果当前聚焦物品被移除，释放空间记忆锁
    updated_context = current_context
    for log in accumulated_logs:
        if log["op_type"] in ("remove", "consume") and current_context:
            if log.get("target_instance_id") == current_context.get("id"):
                logger.info("[Post Process] 释放已移除物品的空间记忆锁")
                updated_context = None

    return {
        "reply_text": reply_text,
        "current_context_item": updated_context,
        "mutation_logs": [],
    }


# ==============================
# 图构建
# ==============================

def build_squirrel_graph():
    """构建新架构 LangGraph。"""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(ExtendedGraphState)

    graph.add_node("input_router", multimodal_identity_router_node)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("conflict_batch_resolver", conflict_batch_resolver_node)
    graph.add_node("confirm_subgraph_handler", confirm_subgraph_handler_node)
    graph.add_node("mutation_executor", mutation_executor_node)
    graph.add_node("query_handler", query_handler_node)
    graph.add_node("post_process", post_process_node)

    # START → input_router（先执行 input_router，再根据结果路由）
    graph.add_edge(START, "input_router")

    # input_router → confirm_subgraph_handler / intent_classifier / post_process
    graph.add_conditional_edges(
        "input_router",
        route_after_input,
        {
            "go_to_confirm_handler": "confirm_subgraph_handler",
            "go_to_intent_classifier": "intent_classifier",
            "end_early": "post_process",
        },
    )

    # intent_classifier → conflict_batch_resolver / query_handler
    graph.add_conditional_edges(
        "intent_classifier",
        route_by_new_intent,
        {
            "mutation": "conflict_batch_resolver",
            "query": "query_handler",
        },
    )

    # conflict_batch_resolver → mutation_executor / post_process
    graph.add_conditional_edges(
        "conflict_batch_resolver",
        route_after_resolver,
        {
            "execute": "mutation_executor",
            "pending": "post_process",
        },
    )

    # confirm_subgraph_handler → mutation_executor / post_process
    graph.add_conditional_edges(
        "confirm_subgraph_handler",
        route_after_confirm,
        {
            "success": "mutation_executor",
            "cancel": "post_process",
        },
    )

    # 汇聚到 post_process
    graph.add_edge("mutation_executor", "post_process")
    graph.add_edge("query_handler", "post_process")
    graph.add_edge("post_process", END)

    return graph.compile()


# ==============================
# 适配函数：ExtendedGraphState → 旧 dict 格式
# ==============================

def extended_to_old_dict(state: ExtendedGraphState, inventory: list[Item] | None = None) -> dict:
    """将新图输出适配为 routes.py 期望的旧格式（含 chat_result + db_operations）。"""
    intent = state.get("intent", "chat")
    reply_text = state.get("reply_text", "")
    mutation_logs = state.get("mutation_logs", [])
    pending_op = state.get("pending_operation")
    pending_selection = state.get("pending_item_selection", [])
    interaction_mode = state.get("interaction_mode", "normal")
    inventory = inventory or state.get("inventory", [])

    # --- 构建 db_operations ---
    db_ops: dict = {"upsert_items": [], "delete_ids": [], "pending_add": [], "pending_consume": {}}

    # 从 mutation_logs 构建 db_ops
    for log in mutation_logs:
        op_type = log.get("op_type")
        instance_id = log.get("target_instance_id", "")
        sku_title = log.get("sku_title", "")
        delta = log.get("delta", 0)
        patch_data = log.get("patch")

        if op_type == "add":
            # 从 pending_add_items 或 mutation_log 构造 Item
            item_data = log.get("item_data", {})
            if item_data:
                item = Item.model_validate(item_data) if isinstance(item_data, dict) else item_data
                db_ops["pending_add"].append(item)
            else:
                # 构造一个最小 Item
                db_ops["pending_add"].append(Item(title=sku_title, count=abs(delta) if delta else 1))

        elif op_type == "update":
            target = next((it for it in inventory if it.id == instance_id), None)
            if target and patch_data:
                patched = target.model_copy(update=patch_data)
                patched.id = target.id
                db_ops["upsert_items"].append(patched)
            elif target:
                db_ops["upsert_items"].append(target)

        elif op_type in ("consume", "remove"):
            target = next((it for it in inventory if it.id == instance_id), None)
            deduct_count = abs(delta)
            if target:
                if deduct_count >= target.count or op_type == "remove":
                    db_ops["delete_ids"].append(instance_id)
                else:
                    new_count = target.count - deduct_count
                    new_pct = max(0, round(new_count / max(target.count, 1) * 100))
                    patched = target.model_copy(update={"count": new_count, "remainingPct": new_pct})
                    patched.id = target.id
                    db_ops["upsert_items"].append(patched)

    # 如果没有 mutation_logs 但有 pending_operation，构建 pending consume/add
    if not mutation_logs and pending_op:
        if pending_op.type in ("consume", "remove"):
            if pending_op.source_batch_ids:
                candidates = [it for it in inventory if it.id in pending_op.source_batch_ids]
            else:
                candidates = _match_items_3tier(inventory, pending_op.target_sku_title)
            db_ops["pending_consume"] = {
                "candidates": candidates[:6] if candidates else [],
                "context": {"consumeAll": pending_op.consume_all, "patch": pending_op.patch},
            }

    # 从 state 中取 pending_add_items（mutation_executor 设置）
    pending_add = state.get("pending_add_items", [])
    if pending_add:
        items = [Item.model_validate(i) if isinstance(i, dict) else i for i in pending_add]
        db_ops["pending_add"] = items

    # --- 构建 chat_result ---
    needs_confirm = (interaction_mode == "pending_selection") or bool(db_ops.get("pending_add") or db_ops.get("pending_consume"))

    chat_result = ChatResult(
        intent=intent,
        replyText=reply_text,
        needsConfirmation=needs_confirm,
    )

    # 有 mutation_logs → 已确认操作（兼容旧 confirmed 路径）
    if mutation_logs:
        chat_result.confirmedItemId = mutation_logs[0].get("target_instance_id", "auto-confirmed")
        if len(mutation_logs) > 1:
            chat_result.confirmedItemIds = [log.get("target_instance_id", "") for log in mutation_logs if log.get("target_instance_id")]

    # --- 构建其他透传字段 ---
    return {
        "chat_result": chat_result,
        "db_operations": db_ops,
        "interaction_mode": interaction_mode,
        "pending_item_selection": pending_selection,
        "pending_operation": pending_op.model_dump() if isinstance(pending_op, PendingOperation) else None,
        "last_added_item": state.get("last_added_item"),
        "current_context_item": state.get("current_context_item"),
        "recipe_recommend": state.get("recipe_recommendation"),
    }


# ==============================
# 入口函数（签名与旧图完全一致）
# ==============================

squirrel_graph = None  # lazy init


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
    current_user_id: str = "default_user",
    current_user_name: str = "主人",
) -> dict:
    """运行新图，返回旧格式 dict 保证兼容性。

    签名与旧 `run_squirrel_graph` 完全一致。
    内部构建 ExtendedGraphState → invoke → extended_to_old_dict。
    """
    global squirrel_graph
    if squirrel_graph is None:
        squirrel_graph = build_squirrel_graph()

    # 将旧 pending_operation dict 转为 PendingOperation
    pop = None
    if pending_operation:
        pop = PendingOperation(
            type=pending_operation.get("type", "consume"),
            target_sku_title=pending_operation.get("target", ""),
            patch=pending_operation.get("patch", {}),
            consume_all=pending_operation.get("consumeAll", False),
            source_batch_ids=pending_operation.get("source_batch_ids", []),
        )

    # 构建新状态
    state: ExtendedGraphState = {
        "raw_text_input": text,
        "image_payloads": [],
        "current_user": UserContext(
            user_id=current_user_id,
            user_name=current_user_name,
            role="member",
            current_zone=None,
        ),
        "intent": "",
        "extracted_entities": {},
        "interaction_mode": interaction_mode if interaction_mode == "pending_selection" else "normal",
        "current_context_item": current_context_item,
        "pending_item_selection": pending_item_selection or [],
        "pending_operation": pop,
        "reply_text": "",
        "recipe_recommendation": None,
        "mutation_logs": [],
        "inventory": inventory or [],
        "user_preference": user_preference,
        "reminder_time": reminder_time,
        "last_added_item": last_added_item,
        "confirmed_item_id": None,
        "confirmed_item_ids": [],
        "confirmed_patch": None,
        "pending_add_items": [],
    }

    result = squirrel_graph.invoke(state)
    return extended_to_old_dict(result, inventory=inventory or [])