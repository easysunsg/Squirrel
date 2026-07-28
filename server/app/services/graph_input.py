"""Input, re-entry, snapshot, and intent nodes."""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from app.db.sqlite import get_active_snapshot, save_snapshot, save_checkpoint, get_checkpoint
from app.models.schemas import ChatOperation, ChatResult, Item, RecipeRequest
from app.models.state import (
    ActionStatus,
    AgentAction,
    ExtendedGraphState,
    PendingOperation,
    UserContext,
    EventType, SystemEvent, generate_idempotency_key, mutation_log_to_event,
    merge_audit_logs,
    version_conflict_check,
)
from app.services.planner import plan_actions
from app.services.capabilities import CapabilityRegistry
from app.services.idempotency import idempotency_service
from app.services.event_bus import event_bus
from app.services.cache import get_recipe_cache, set_recipe_cache
from app.services.llm import llm_service
from app.services.markdown import item_status
from app.services.parser import (
    build_chat_result,
    days_from_now,
    extract_expire_patch,
    extract_location_update,
    extract_target_title,
    extract_remaining_patch,
    extract_search_keyword,
    infer_search_terms,
    guess_space,
    is_query_total,
    parse_add_items,
    parse_multi_selection,
)
from app.services.spatial_service import spatial_service
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)

from app.services.graph_utils import (
    _build_candidate_entries,
    _build_candidate_lines,
    _build_context_item,
    _build_multi_consume_allocation,
    _build_multi_consume_reply,
    _build_multi_remove_reply,
    _build_multi_update_reply,
    _calc_expire_days,
    _is_pronoun_or_garbage_target,
    _match_items_3tier,
    match_search_items,
    summarize_titles,
)

# ==============================
# 节点 0a: ReEntryRouter (重入路由)
# ==============================

_REENTRY_SHARED_FLAG = "_snapshot_was_restored"


def re_entry_router_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【重入路由】判定当前是 NEW 还是 RESUME 模式。

    检查 DB 中是否存在活跃挂起快照。
    如果存在 → 标记 snapshot_was_restored → 下游节点恢复现场。
    如果不存在 → 正常 NEW 流程。
    """
    current_user = state.get("current_user")
    session_id = current_user.user_id if current_user else "default_user"
    snapshot = None
    try:
        from app.db.sqlite import connect, delete_snapshot
        with connect() as conn:
            snapshot = get_active_snapshot(conn, session_id)
            if snapshot:
                # Snapshots are one-shot continuations. A newly suspended run
                # will write a replacement snapshot when necessary.
                delete_snapshot(conn, snapshot["snapshot_id"])
    except Exception:
        logger.exception("[ReEntryRouter] DB 查询快照失败，将按 NEW 模式处理")

    if snapshot and snapshot.get("is_suspended"):
        restored = _build_reentry_entities(snapshot)
        pending_operation = restored["pending_operation"]
        if pending_operation and not isinstance(pending_operation, PendingOperation):
            pending_operation = PendingOperation.model_validate(pending_operation)
        logger.info("[ReEntryRouter] 发现活跃快照 session=%s version=%d", session_id, snapshot["graph_version"])
        return {
            _REENTRY_SHARED_FLAG: True,
            "interaction_mode": restored["interaction_mode"],
            "pending_item_selection": restored["pending_item_selection"],
            "pending_operation": pending_operation,
            "current_context_item": restored["current_context_item"],
            "mutation_logs": restored["mutation_logs"],
            "reply_text": "",
        }

    logger.info("[ReEntryRouter] 无挂起快照 -> NEW 模式")
    return {
        _REENTRY_SHARED_FLAG: False,
    }


def _build_reentry_entities(snapshot: dict) -> dict:
    """从快照数据构建重入实体，供下游节点判断交互上下文。"""
    ws = snapshot.get("workspace_snapshot", {})
    return {
        "interaction_mode": ws.get("interaction_mode", "pending_selection"),
        "pending_item_selection": ws.get("pending_item_selection", []),
        "pending_operation": ws.get("pending_operation"),
        "current_context_item": ws.get("current_context_item"),
        "mutation_logs": ws.get("mutation_logs", []),
    }


def route_after_reentry(state: ExtendedGraphState) -> Literal["resume", "new"]:
    """【条件路由】根据快照状态分流。"""
    if state.get(_REENTRY_SHARED_FLAG):
        return "resume"
    return "new"


# ==============================
# 节点 0b: ReferenceResolver (指代消解)
# ==============================

def reference_resolver_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【指代消解】将当前文本与跨轮上下文关联。

    解析用户口语中的"它"、"这个"、"那个"、"它们"等代词，
    将其替换成 current_context_item 中的实际物品。
    """
    raw_text = state.get("raw_text_input", "")
    current_context = state.get("current_context_item")
    entities = state.get("extracted_entities", {})

    target = entities.get("target", "")
    if not target or _is_pronoun_or_garbage_target(target):
        if current_context and current_context.get("title"):
            resolved_title = current_context["title"]
            logger.info("[RefResolver] 代词消解: '%s' -> '%s' (来自上下文)", target or "(空)", resolved_title)
            return {
                "extracted_entities": {
                    **entities,
                    "target": resolved_title,
                    "resolved_from_context": True,
                    "original_target": target,
                },
            }

    return {
        "extracted_entities": {
            **entities,
            "resolved_from_context": False,
        },
    }


# ==============================
# 节点 0c: GoalManager (目标管理)
# ==============================

def goal_manager_node(state: ExtendedGraphState) -> Dict[str, Any]:
    entities = state.get("extracted_entities", {})
    resolved_target = entities.get("target", "")
    resolved = entities.get("resolved_from_context", False)
    logger.info("[GoalManager] target='%s' resolved=%s", resolved_target, resolved)
    return {
        "_goal_resolved": True,
        "_goal_target": resolved_target,
    }


# ==============================
# 节点 0d: SnapshotStore (快照管理)
# ==============================

def snapshot_store_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【快照管理】挂起时封存现场快照到 DB。

    当检测到以下情况时保存挂起快照：
    - pending_selection 模式（多选确认）
    - 参数缺失（missing_parameters）
    - 高风险操作被拦截（is_blocked）
    - 无效操作（is_invalid）
    - 预算超限（budget_exceeded）
    """
    entities = state.get("extracted_entities", {})
    pending_op = state.get("pending_operation")
    interaction_mode = state.get("interaction_mode", "normal")
    reply_text = state.get("reply_text", "")
    missing = state.get("missing_parameters", [])
    is_blocked = state.get("is_blocked", False)
    is_invalid = state.get("is_invalid", False)
    budget_exceeded = state.get("budget_exceeded", False)

    # 判定是否需要挂起
    needs_suspend = (
        (interaction_mode == "pending_selection" and pending_op)
        or bool(missing)
        or is_blocked
        or is_invalid
        or budget_exceeded
    )

    if needs_suspend:
        # 推导挂起原因
        if is_blocked:
            suspension_reason = "POLICY_BLOCKED"
        elif is_invalid:
            suspension_reason = "INVALID_OPERATION"
        elif budget_exceeded:
            suspension_reason = "BUDGET_EXCEEDED"
        elif bool(missing):
            suspension_reason = "MISSING_PARAMETERS"
        else:
            suspension_reason = "CONFIRMATION"

        try:
            from app.db.sqlite import connect

            snapshot_data = {
                "is_suspended": True,
                "execution_mode": "SUSPENDED",
                "suspension_reason": suspension_reason,
                "workspace_snapshot": {
                    "interaction_mode": interaction_mode,
                    "pending_item_selection": state.get("pending_item_selection", []),
                    "pending_operation": pending_op.model_dump() if hasattr(pending_op, "model_dump") else pending_op,
                    "current_context_item": state.get("current_context_item"),
                    "mutation_logs": state.get("mutation_logs", []),
                    "reply_text": reply_text,
                },
                "missing_parameters": missing,
                "blocked_action_id": None,
                "raw_user_input": state.get("raw_text_input", ""),
            }

            with connect() as conn:
                save_snapshot(
                    conn=conn,
                    snapshot_id=f"snap_{uuid4().hex[:12]}",
                    session_id=(state.get("current_user").user_id if state.get("current_user") else "default_user"),
                    graph_version=1,
                    snapshot_data=snapshot_data,
                    ttl_minutes=60,
                )
            logger.info("[SnapshotStore] 已保存挂起快照 reason=%s", suspension_reason)
        except Exception:
            logger.exception("[SnapshotStore] 保存快照失败")

    return {
        "reply_text": reply_text,
    }


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
    if current_mode == "pending_selection":
        # 用 parse_multi_selection 判断是否为有效的选择题回复
        from app.services.parser import parse_multi_selection
        pending_count = len(state.get("pending_item_selection", []))
        parsed = parse_multi_selection(raw_text, pending_count)

        # 包含式 escape 检测：兼容"算了，不要了"等带标点的变体
        is_escape = any(ew in raw_text for ew in _ESCAPE_WORDS) or parsed == "cancel"
        if is_escape:
            logger.info("[Input Router] 检测到强中断，重置为 normal 模式")
            return {
                "interaction_mode": "normal",
                "pending_item_selection": [],
                "pending_operation": None,
                "reply_text": f"好滴{user_name}，已经帮您取消了刚才的操作。咱们重新开始，您想处理点什么物资？",
            }

        # 非有效选择输入（如打招呼、闲聊）→ 自动重置 pending 状态
        if parsed is None:
            logger.info("[Input Router] 检测到非选择输入「%s」，自动清除待选状态，走正常意图识别", raw_text)
            state_updates["interaction_mode"] = "normal"
            state_updates["pending_item_selection"] = []
            state_updates["pending_operation"] = None
            # 不回显"已取消"，直接走意图分类

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
    # 通过 state_updates 重置了 pending → 走正常意图分类
    if state.get("interaction_mode") in ("pending_selection", "pending_confirm"):
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


def _resolve_inventory_followup(
    text: str,
    last_added: dict | None,
    current_context: dict | None,
    inventory: list[Item],
) -> Dict[str, Any] | None:
    """Resolve common inventory follow-ups before an LLM can replace their target."""
    import re as re_mod

    focus = last_added or current_context
    focus_item = None
    if focus:
        focus_item = next((it for it in inventory if it.id == focus.get("id")), None)
        if not focus_item:
            focus_item = next((it for it in inventory if it.title == focus.get("title")), None)

    if "备注" in text and any(word in text for word in ("加上", "补上", "写上", "备注")):
        if not focus_item:
            return None
        before_remark = re_mod.split(r"[，,]?你?(?:把)?备注", text, maxsplit=1)[0]
        remark = before_remark.strip(" ，,。")
        remark = re_mod.sub(r"^每盒大概有\s*", "每盒约 ", remark)
        remark = re_mod.sub(r"(\d+)\s*(克|g|kg)", r"\1 \2", remark, flags=re_mod.I)
        if not remark:
            return None
        return {
            "intent": "update_remark",
            "reply_text": f"准备为「{focus_item.title}」追加备注。",
            "extracted_entities": {
                "target": focus_item.title,
                "target_item_id": focus_item.id,
                "patch": {"remarkAppend": remark},
            },
            "current_context_item": _build_context_item(focus_item),
        }

    expire_patch = extract_expire_patch(text)
    if expire_patch and "保质期" in text and focus_item:
        return {
            "intent": "update_expiry",
            "reply_text": f"准备更新「{focus_item.title}」的保质期。",
            "extracted_entities": {
                "target": focus_item.title,
                "target_item_id": focus_item.id,
                "patch": expire_patch,
            },
            "current_context_item": _build_context_item(focus_item),
        }

    if re_mod.search(r"洗一盒|洗一份|准备吃|下午吃", text):
        target = extract_target_title(text)
        if target:
            matched = next((it for it in inventory if it.title == target), None)
            if matched:
                return {
                    "intent": "consume",
                    "reply_text": f"准备扣减「{matched.title}」1{matched.unit}。",
                    "extracted_entities": {
                        "target": matched.title,
                        "target_item_id": matched.id,
                        "patch": {"deductCount": 1},
                    },
                    "current_context_item": _build_context_item(matched),
                }
    return None


def _resolve_batch_split_followup(text: str, inventory: list[Item]) -> Dict[str, Any] | None:
    """Recognize a correction that splits part of an existing batch into a variant/location."""
    import re as re_mod

    match = re_mod.search(
        r"(?P<title>[^，,。]+?)里有\s*(?P<count>\d+)\s*"
        r"(?P<unit>袋|瓶|盒|个|件|包|罐|本|条|把|颗|斤|克|g|kg)"
        r"\s*是(?P<variant>.+?)的[，,]\s*放(?:到|在|进)?(?P<location>.+?)。?$",
        text,
        re_mod.I,
    )
    if not match:
        return None

    source_title = match.group("title").strip(" ，,。")
    source = next((item for item in inventory if item.title == source_title), None)
    count = int(match.group("count"))
    if not source or count <= 0 or count > source.count:
        return None

    variant = match.group("variant").strip(" ，,。的")
    location = re_mod.sub(r"[了吧呢]+$", "", match.group("location").strip(" ，,。"))
    location = re_mod.sub(r"里$", "", location).strip() or "默认层架"
    if not variant:
        return None

    new_title = variant if source_title in variant else f"{variant}{source_title}"
    space_id, space_name = guess_space(location)
    split_item = source.model_copy(update={
        "id": None,
        "instanceId": None,
        "skuId": None,
        "title": new_title,
        "count": count,
        "unit": match.group("unit"),
        "spaceId": space_id,
        "spaceName": space_name,
        "location": location,
        "remainingPct": 100,
        "remark": f"从「{source.title}」批次拆分；{variant}",
    })
    return {
        "intent": "add",
        "reply_text": f"准备从「{source.title}」中拆出 {count}{source.unit}「{new_title}」。",
        "extracted_entities": {
            "target": new_title,
            "items": [split_item.model_dump()],
            "split_source": {
                "id": source.id,
                "title": source.title,
                "count": count,
            },
        },
        "current_context_item": _build_context_item(source),
    }


def intent_classifier_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【意图分类】LLM 分类 + rule fallback + 近指代消解。"""
    text = state.get("raw_text_input", "")
    inventory = state.get("inventory", [])
    last_added = state.get("last_added_item")
    current_context = state.get("current_context_item")

    if any(term in text for term in ("采购清单", "购物清单", "待购清单")) and any(
        term in text for term in ("加入", "加到", "加上", "添加")
    ):
        import re as re_mod

        title_match = re_mod.search(r"把\s*(.+?)\s*(?:加入|加到|添加到)", text)
        if not title_match:
            title_match = re_mod.search(r"(?:加上|添加)\s*[\"“]?(.+?)[\"”]?(?:。|$)", text)
        title = title_match.group(1).strip(" \"“”。，,") if title_match else ""
        list_match = re_mod.search(r"((?:未来|周末|家庭|我们的)?(?:采购|购物|待购)清单)", text)
        list_name = list_match.group(1) if list_match else "采购清单"
        list_name = list_name.removeprefix("我们的")
        return {
            "intent": "shopping_add",
            "reply_text": f"正在将「{title}」加入{list_name}。",
            "extracted_entities": {
                "target": title,
                "list_name": list_name,
                "count": 1,
                "unit": "个",
            },
            "last_added_item": last_added,
            "current_context_item": current_context,
        }

    is_constrained_search = (
        (
            any(phrase in text for phrase in ("还有别的", "有没有别的", "还有其他", "有没有其他"))
            and any(term in text for term in ("冷藏层", "冷冻层", "冰箱", "柜", "生鲜", "食材", "食品", "水果", "蔬菜", "盘装", "饮料"))
        )
        or ("饮料" in text and any(term in text for term in ("什么", "还有", "还剩", "有没有")))
    )
    if is_constrained_search:
        return {
            "intent": "search_query",
            "reply_text": "正在帮你搜索相关库存。",
            "extracted_entities": {},
            "last_added_item": last_added,
            "current_context_item": current_context,
        }

    batch_split = _resolve_batch_split_followup(text, inventory)
    if batch_split:
        return batch_split

    if is_query_total(text):
        mentioned_titles = {item.title for item in inventory if item.title and item.title in text}
        if mentioned_titles:
            # Prefer the shortest mentioned title as the product family root: 可乐 over 无糖可乐.
            target = min(mentioned_titles, key=len)
            return {
                "intent": "quantity_query",
                "reply_text": f"正在统计「{target}」的全部库存。",
                "extracted_entities": {"target": target},
                "last_added_item": last_added,
                "current_context_item": current_context,
            }

    followup = _resolve_inventory_followup(text, last_added, current_context, inventory)
    if followup:
        return followup

    # 近指代优先
    near_ref = _resolve_near_reference(text, last_added, inventory)
    if near_ref:
        return near_ref

    # LLM 分类
    chat_result = None
    if llm_service.enabled:
        try:
            inventory_summary = summarize_titles(inventory, limit=10) if inventory else "库存为空"
            llm_result = llm_service.classify_intent(text, inventory_summary, current_context)
            intent = llm_result.get("intent", "unknown")
            entities = llm_result.get("entities", {})

            if intent != "unknown":
                reply_text = f"已识别意图：{intent}"
                extracted: Dict[str, Any] = {}

                if intent == "add":
                    parsed_items = parse_add_items(text)
                    reply_text = f"已识别出 {len(parsed_items)} 件物品，准备入库。"
                    extracted["items"] = [item.model_dump() for item in parsed_items]
                    extracted["item_count"] = len(parsed_items)

                elif intent in ("consume", "remove"):
                    target = entities.get("target")
                    # 代词/垃圾 target 检测：如果 LLM 提取的 target 是代词或"已处理过的物品"等
                    # 无意义短语，忽略它，回退到 current_context
                    if target and _is_pronoun_or_garbage_target(target):
                        target = None
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
                    if target and _is_pronoun_or_garbage_target(target):
                        target = None
                    if not target and current_context and current_context.get("title"):
                        target = current_context["title"]
                    location = entities.get("location")
                    if target and location:
                        extracted["target"] = target
                        extracted["patch"] = {"location": location}
                    elif target and not location:
                        reply_text = "请问你想把物品放到哪里？"

                elif intent in ("update_expiry", "update_remark"):
                    target = entities.get("target")
                    if not target and current_context and current_context.get("title"):
                        target = current_context["title"]
                    expire_days = entities.get("expire_days")
                    if intent == "update_expiry" and target and expire_days is not None:
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
        target = op.target
        # 规则 fallback 中同样应用代词/垃圾 target 检测 → 回退到上下文
        if target and _is_pronoun_or_garbage_target(target):
            target = None
        # 如果规则引擎没能提取到 target（如"丢了吧，这个已经处理过了"无法被正则匹配）
        # 且存在跨轮上下文，用上下文补全
        if not target and current_context and current_context.get("title"):
            target = current_context["title"]
        entities["target"] = target
        entities["items"] = [
            operation.item.model_dump()
            for operation in fallback.operations
            if operation.item is not None
        ]
        if op.patch:
            entities["patch"] = op.patch
    if intent in ("update_expiry", "update_remark") and not entities.get("target"):
        focus = last_added or current_context
        if focus and focus.get("title"):
            entities["target"] = focus["title"]
            entities["target_item_id"] = focus.get("id")
    return {
        "intent": intent,
        "reply_text": fallback.replyText,
        "extracted_entities": entities,
        "last_added_item": last_added,
        "current_context_item": current_context,
    }


