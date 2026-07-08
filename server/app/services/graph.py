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


def _is_pronoun_or_garbage_target(target: str) -> bool:
    """检测 LLM 提取的 target 是否为代词或垃圾短语，需回退到上下文。"""
    import re as re_mod
    pronouns = {"这个", "那个", "这些", "那些", "它", "它们", "这东西", "那东西",
                "这些东西", "那些东西", "这", "那", "该物品", "刚才说的", "上回说的"}
    if target in pronouns:
        return True
    # 以常见中文代词开头的短语 → 也是指代
    if any(target.startswith(p) for p in ("这个", "那个", "这些", "那些", "它", "它们", "这东西", "那东西", "该物品")):
        return True
    # 包含"处理过的/已处理的/吃过的/用过的"等说明性后缀 → 用户是在解释原因
    if re_mod.search(r"已?[处理吃用]\s*过\s*的", target):
        return True
    # 纯说明性短语 / 垃圾值——以动词/形容词开头且长度超过 3 个字
    garbage_prefixes = ("已处理", "处理过", "吃过", "用过", "刚刚", "刚才", "那个", "已经")
    if any(target.startswith(p) for p in garbage_prefixes) and len(target) > 3:
        return True
    return False


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
# 节点 0a: ReEntryRouter (重入路由)
# ==============================

_REENTRY_SHARED_FLAG = "_snapshot_was_restored"


def re_entry_router_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【重入路由】判定当前是 NEW 还是 RESUME 模式。

    检查 DB 中是否存在活跃挂起快照。
    如果存在 → 标记 snapshot_was_restored → 下游节点恢复现场。
    如果不存在 → 正常 NEW 流程。
    """
    import json
    session_id = "default_session"
    snapshot = None
    try:
        from app.db.sqlite import connect
        with connect() as conn:
            snapshot = get_active_snapshot(conn, session_id)
    except Exception:
        logger.exception("[ReEntryRouter] DB 查询快照失败，将按 NEW 模式处理")

    if snapshot and snapshot.get("is_suspended"):
        # 恢复快照中的状态到 workspace
        logger.info("[ReEntryRouter] 发现活跃快照 session=%s version=%d", session_id, snapshot["graph_version"])
        return {
            _REENTRY_SHARED_FLAG: True,
            "extracted_entities": {
                **_build_reentry_entities(snapshot),
            },
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
                    session_id="default_session",
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
            llm_result = llm_service.classify_intent(text, inventory_summary, current_context)
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
        target = op.target
        # 规则 fallback 中同样应用代词/垃圾 target 检测 → 回退到上下文
        if target and _is_pronoun_or_garbage_target(target):
            target = None
        # 如果规则引擎没能提取到 target（如"丢了吧，这个已经处理过了"无法被正则匹配）
        # 且存在跨轮上下文，用上下文补全
        if not target and current_context and current_context.get("title"):
            target = current_context["title"]
        entities["target"] = target
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


# ==============================
# 节点 3a: ParameterResolver (参数解析器)
# ==============================

def parameter_resolver_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【参数解析器】校验参数完整性，检测缺失参数。

    检查 intent 所需的参数是否齐全：
    - add: 需要 items 或 target
    - consume/remove: 需要 target
    - update_location: 需要 target + location
    - update_expiry: 需要 target + expire_days
    """
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    target = entities.get("target")
    items_data = entities.get("items", [])
    patch = entities.get("patch") or {}

    missing: List[str] = []

    if intent in ("add",):
        if not target and not items_data:
            missing.append("target_items")

    elif intent in ("consume", "remove"):
        if not target:
            missing.append("target")

    elif intent == "update_location":
        if not target:
            missing.append("target")
        if not patch.get("location") and not entities.get("location"):
            missing.append("location")

    elif intent == "update_expiry":
        if not target:
            missing.append("target")
        if not patch.get("expireDate") and not entities.get("expire_days"):
            missing.append("expire_date")

    # 如果有缺失参数，设置回复文本
    if missing:
        missing_names = {
            "target_items": "物品名称或数量",
            "target": "物品名称",
            "location": "目标位置",
            "expire_date": "保质期日期",
        }
        missing_desc = "、".join(missing_names.get(m, m) for m in missing)
        return {
            "missing_parameters": missing,
            "reply_text": f"参数不完整，缺少：{missing_desc}。请补充完整后重试。",
            "extracted_entities": {
                **entities,
                "missing_parameters": missing,
            },
        }

    return {}


def route_after_parameter_resolve(state: ExtendedGraphState) -> Literal["ready", "missing"]:
    """【条件路由】参数完整 → 继续 / 参数缺失 → 挂起。"""
    missing = state.get("missing_parameters", [])
    if missing:
        return "missing"
    return "ready"


# ==============================
# 节点 3b: PolicyEngine (策略引擎)
# ==============================

# 预定义策略规则
_DEFAULT_POLICIES = [
    {
        "rule_id": "risk_high_consumption",
        "rule_name": "大额消耗拦截",
        "description": "单次消耗数量超过10件时触发风控",
        "rule_type": "risk_control",
        "conditions": {"intent": "consume", "deduct_count__gt": 10},
        "action": "warn",
    },
    {
        "rule_id": "risk_bulk_remove",
        "rule_name": "批量删除拦截",
        "description": "批量删除超过5件物品时触发风控",
        "rule_type": "risk_control",
        "conditions": {"intent": "remove", "batch_count__gt": 5},
        "action": "block",
    },
    {
        "rule_id": "risk_expired_item",
        "rule_name": "过期物品操作拦截",
        "description": "操作已过期物品时发出警告",
        "rule_type": "risk_control",
        "conditions": {"intent__in": ["consume", "remove"], "item_is_expired": True},
        "action": "warn",
    },
]


def policy_engine_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【策略引擎】执行预定义策略规则检测。

    检查当前操作是否触发了任何风控策略。
    """
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    inventory = state.get("inventory", [])
    target = entities.get("target")

    triggered_rules: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for rule in _DEFAULT_POLICIES:
        conditions = rule["conditions"]
        matched = False

        if conditions.get("intent") == intent:
            # 大额消耗检测
            if "deduct_count__gt" in conditions:
                patch = entities.get("patch") or {}
                deduct_count = patch.get("deductCount") or 1
                if isinstance(deduct_count, (int, float)) and deduct_count > conditions["deduct_count__gt"]:
                    matched = True
                    warnings.append(f"单次消耗{deduct_count}件，触发大额消耗风控")

            # 批量删除检测
            if "batch_count__gt" in conditions:
                pending_ids = state.get("pending_item_selection", [])
                if len(pending_ids) > conditions["batch_count__gt"]:
                    matched = True
                    warnings.append(f"批量删除{len(pending_ids)}件，触发批量删除风控")

            # 过期物品检测
            if "item_is_expired" in conditions and target:
                from datetime import date
                for item in inventory:
                    if item.title == target and item.expireDate:
                        try:
                            expire_date = datetime.strptime(item.expireDate, "%Y-%m-%d").date()
                            if expire_date < date.today():
                                matched = True
                                warnings.append(f"「{item.title}」已过期({item.expireDate})，请谨慎操作")
                                break
                        except (ValueError, TypeError):
                            pass

        if matched:
            triggered_rules.append({
                "rule_id": rule["rule_id"],
                "rule_name": rule["rule_name"],
                "action": rule["action"],
                "warnings": warnings,
            })

    if triggered_rules:
        # 检查是否有 block 级别的规则
        blocked = any(r["action"] == "block" for r in triggered_rules)
        if blocked:
            block_reasons = [r["warnings"][0] if r["warnings"] else r["rule_name"] for r in triggered_rules if r["action"] == "block"]
            return {
                "policy_violations": triggered_rules,
                "is_blocked": True,
                "reply_text": "⚠️ " + "；".join(block_reasons) + "。操作已被拦截，如需执行请联系管理员。",
                "interaction_mode": "normal",
                "pending_operation": None,
            }

        # warn 级别：在回复中追加警告
        all_warnings = []
        for r in triggered_rules:
            all_warnings.extend(r["warnings"])
        existing_reply = state.get("reply_text", "")
        warn_text = "⚠️ " + "；".join(all_warnings[:3])
        return {
            "policy_violations": triggered_rules,
            "is_blocked": False,
            "reply_text": f"{warn_text}\n\n{existing_reply}" if existing_reply else warn_text,
        }

    return {
        "policy_violations": [],
        "is_blocked": False,
    }


def route_after_policy(state: ExtendedGraphState) -> Literal["blocked", "ready"]:
    """【条件路由】策略检查通过 → 继续 / 被拦截 → post_process。"""
    if state.get("is_blocked"):
        return "blocked"
    return "ready"


# ==============================
# 节点 3c: PreExecutionChecker (预执行检查器)
# ==============================

def pre_execution_checker_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【预执行检查器】静态拦截与风控判定。

    在参数解析和策略引擎之后，做最终执行前检查。
    检查项：
    1. 高危操作是否需要用户确认
    2. 操作是否涉及已删除/不存在的物品
    3. 操作是否合理（如消耗数量 > 库存数量）
    """
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    inventory = state.get("inventory", [])
    target = entities.get("target")
    pending_op = state.get("pending_operation")

    checks: List[str] = []

    # 检查1：消耗数量 > 库存数量
    if intent == "consume" and target:
        patch = entities.get("patch") or {}
        deduct_count = patch.get("deductCount") or 1
        matched_items = [item for item in inventory if item.title == target]
        if matched_items:
            total_count = sum(item.count for item in matched_items)
            if isinstance(deduct_count, (int, float)) and deduct_count > total_count:
                checks.append(f"消耗数量({deduct_count})超过库存总量({total_count})，已自动调整为{total_count}")
                # 自动修正
                patch["deductCount"] = total_count
                return {
                    "pre_execution_checks": checks,
                    "extracted_entities": {**entities, "patch": patch},
                    "reply_text": state.get("reply_text", "") + ("\n" + checks[0] if checks else ""),
                    "needs_correction": True,
                }

    # 检查2：操作不存在物品
    if intent in ("consume", "remove", "update_location", "update_expiry") and target:
        matched = [item for item in inventory if item.title == target]
        if not matched:
            return {
                "pre_execution_checks": [f"未找到物品「{target}」"],
                "is_invalid": True,
                "reply_text": f"库存中没有找到「{target}」，请检查物品名称是否正确。",
            }

    return {
        "pre_execution_checks": checks,
        "is_invalid": False,
        "needs_correction": False,
    }


def route_after_pre_execution(state: ExtendedGraphState) -> Literal["invalid", "ready"]:
    """【条件路由】检查通过 → 继续 / 无效 → post_process。"""
    if state.get("is_invalid"):
        return "invalid"
    return "ready"


# ==============================
# 节点 3d: BudgetGuard (预算守卫)
# ==============================

def budget_guard_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【预算守卫】执行预算控制。

    当前实现：
    - 基于 loop_depth 的深度控制（已在 LoopGuard 中实现）
    - 基于操作数量的批量控制
    - 预留：基于 token 消耗的预算控制

    此节点作为扩展点，后续可接入外部预算服务。
    """
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    loop_depth = state.get("loop_depth", 0)
    max_depth = state.get("max_depth", 5)

    budget_checks: List[str] = []

    # 深度检查
    if loop_depth >= max_depth:
        budget_checks.append(f"执行深度({loop_depth})已达到上限({max_depth})")
        return {
            "budget_exceeded": True,
            "budget_checks": budget_checks,
            "reply_text": "操作深度已到达上限，请简化操作后重试。",
        }

    # 批量操作数量检查
    if intent == "add":
        items_data = entities.get("items", [])
        if len(items_data) > 20:
            budget_checks.append(f"批量添加({len(items_data)}件)超过单次上限(20件)")
            return {
                "budget_exceeded": True,
                "budget_checks": budget_checks,
                "reply_text": f"单次最多添加20件物品，当前{len(items_data)}件已超出限制，请分批添加。",
            }

    return {
        "budget_exceeded": False,
        "budget_checks": budget_checks,
    }


def route_after_budget(state: ExtendedGraphState) -> Literal["exceeded", "ready"]:
    """【条件路由】预算充足 → 继续 / 超出 → 挂起。"""
    if state.get("budget_exceeded"):
        return "exceeded"
    return "ready"


# ==============================
# 节点 3e: ConsistencyChecker (一致性检查器)
# ==============================

def consistency_checker_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【一致性检查器】约束一致性检查。

    检查项：
    1. 同一物品不能同时出现在 add 和 remove 操作中
    2. 操作目标不能同时包含矛盾和互斥的属性修改
    """
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    patch = entities.get("patch") or {}

    consistency_issues: List[str] = []

    # 检查互斥的属性修改
    if intent == "update_location" and intent == "update_expiry":
        consistency_issues.append("不能同时修改位置和保质期")

    # 检查 location 和 expiry 的互斥
    if patch:
        has_location = "location" in patch
        has_expiry = "expireDate" in patch
        if has_location and has_expiry:
            consistency_issues.append("同一操作中不能同时修改位置和保质期，请分步操作")

    if consistency_issues:
        return {
            "consistency_issues": consistency_issues,
            "is_inconsistent": True,
            "reply_text": "操作存在一致性冲突：" + "；".join(consistency_issues),
        }

    return {
        "consistency_issues": [],
        "is_inconsistent": False,
    }


def route_after_consistency(state: ExtendedGraphState) -> Literal["inconsistent", "ready"]:
    """【条件路由】一致 → 继续 / 不一致 → 退回。"""
    if state.get("is_inconsistent"):
        return "inconsistent"
    return "ready"


# ==============================
# 节点 3f: CapabilityRouter (能力路由器)
# ==============================

def capability_router_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【能力路由器】按 intent 路由到对应的能力域。

    将 intent 映射到具体的 capability 名称，
    并生成对应的 AgentAction 供后续执行。
    """
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    pending_op = state.get("pending_operation")

    # intent → capability 映射
    capability_map = {
        "add": "inventory",
        "consume": "inventory",
        "remove": "inventory",
        "update_location": "inventory",
        "update_expiry": "inventory",
        "update_remaining": "inventory",
        "expiry_query": "expiration",
        "location_query": "inventory",
        "quantity_query": "inventory",
        "search_query": "inventory",
        "idle_query": "inventory",
        "recipe": "recommendation",
        "chat": "chat",
    }

    capability = capability_map.get(intent, "chat")
    target = entities.get("target", "")

    # 生成 AgentAction
    action = AgentAction(
        idempotency_key=generate_idempotency_key(
            session_id="default_session",
            graph_version=0,
            tool_name=f"{capability}_{intent}",
            arguments={"target": target, "intent": intent},
        ),
        capability=capability,
        tool_name=f"{capability}_{intent}",
        arguments={
            "target": target,
            "intent": intent,
            "extracted_entities": entities,
        },
        status=ActionStatus.PENDING,
        risk_level=_determine_risk_level(intent, entities),
    )

    return {
        "capability": capability,
        "current_action": action,
    }


def _determine_risk_level(intent: str, entities: dict) -> str:
    """根据意图和参数确定风险等级。"""
    high_risk_intents = {"remove", "consume"}
    medium_risk_intents = {"update_location", "update_expiry", "update_remaining"}

    if intent in high_risk_intents:
        patch = entities.get("patch") or {}
        deduct_count = patch.get("deductCount") or 1
        if isinstance(deduct_count, (int, float)) and deduct_count > 5:
            return "HIGH"
        return "MEDIUM"

    if intent in medium_risk_intents:
        return "MEDIUM"

    return "LOW"


def route_after_capability(state: ExtendedGraphState) -> Literal["mutation", "query"]:
    """【条件路由】mutation → 原有 mutation 路由 / query → 原有 query 路由。"""
    intent = state.get("intent", "chat")
    if intent in ("add", "consume", "remove", "update_location", "update_expiry", "update_remaining"):
        return "mutation"
    return "query"


# ==============================
# 节点 4a: ToolExecutor (工具执行器)
# ==============================

def tool_executor_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【工具执行器】通过 CapabilityRegistry 执行具体操作。

    流程：
    1. 从 state 中获取 current_action
    2. 查 CapabilityRegistry 获取对应能力域
    3. 执行 idempotency check
    4. 调用能力域的 execute() 方法
    """
    from app.db.sqlite import connect

    current_action = state.get("current_action")
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    inventory = state.get("inventory", [])
    pending_op = state.get("pending_operation")
    confirmed_item_id = state.get("confirmed_item_id")
    confirmed_item_ids = state.get("confirmed_item_ids", [])
    confirmed_patch = state.get("confirmed_patch")

    # 构建执行上下文
    context = {
        "inventory": inventory,
        "user_id": state.get("current_user", UserContext(user_id="default", user_name="主人")).user_id,
        "user_name": state.get("current_user", UserContext(user_id="default", user_name="主人")).user_name,
        "pending_operation": pending_op,
        "confirmed_item_id": confirmed_item_id,
        "confirmed_item_ids": confirmed_item_ids,
        "confirmed_patch": confirmed_patch,
        "user_preference": state.get("user_preference", "无特殊要求"),
        "reminder_time": state.get("reminder_time", ""),
    }

    # 如果没有 current_action，通过 intent 直接查找 capability
    if not current_action:
        capability_name = _intent_to_capability(intent)
        cap = CapabilityRegistry.get(capability_name)
        if not cap:
            logger.warning("[ToolExecutor] 未找到能力域: %s", capability_name)
            return {"reply_text": f"无法处理 {intent} 类型的操作。"}

        # 构造临时 AgentAction
        current_action = AgentAction(
            idempotency_key=generate_idempotency_key(
                session_id="default_session",
                graph_version=0,
                tool_name=f"{capability_name}_{intent}",
                arguments={"target": entities.get("target", ""), "intent": intent, "extracted_entities": entities},
            ),
            capability=capability_name,
            tool_name=f"{capability_name}_{intent}",
            arguments={"target": entities.get("target", ""), "intent": intent, "extracted_entities": entities},
            status=ActionStatus.PENDING,
        )

    # 查找能力域
    cap = CapabilityRegistry.get_for_action(current_action)
    if not cap:
        logger.warning("[ToolExecutor] 未找到能力域: %s", current_action.capability)
        return {"reply_text": f"无法处理 {current_action.capability} 类型的操作。"}

    # 幂等性检查
    try:
        with connect() as conn:
            can_execute, cached_result = idempotency_service.check_and_acquire(
                current_action.idempotency_key, conn
            )
            if not can_execute and cached_result:
                logger.info("[ToolExecutor] 命中幂等缓存 %s", current_action.idempotency_key[:20])
                return {
                    **cached_result,
                    "idempotency_hit": True,
                }
    except Exception:
        logger.exception("[ToolExecutor] 幂等检查失败，继续执行")
        can_execute = True

    # 执行
    logger.info("[ToolExecutor] 执行: %s/%s", current_action.capability, current_action.tool_name)
    result = cap.execute(current_action, context)

    # 完成幂等锁
    try:
        with connect() as conn:
            idempotency_service.complete(current_action.idempotency_key, conn, result)
    except Exception:
        logger.exception("[ToolExecutor] 幂等完成标记失败")

    return result


def _intent_to_capability(intent: str) -> str:
    """将 intent 映射到 capability 名称。"""
    mapping = {
        "add": "inventory", "consume": "inventory", "remove": "inventory",
        "update_location": "inventory", "update_expiry": "inventory", "update_remaining": "inventory",
        "expiry_query": "expiration", "location_query": "inventory", "quantity_query": "inventory",
        "search_query": "inventory", "idle_query": "inventory", "recipe": "recommendation",
        "chat": "chat",
    }
    return mapping.get(intent, "chat")


# ==============================
# 节点 4b: ResultValidator (结果校验器)
# ==============================

def result_validator_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【结果校验器】校验执行结果是否合法。

    检查项：
    1. mutation_logs 是否有效
    2. 是否有错误信息
    3. 结果是否为空
    """
    mutation_logs = state.get("mutation_logs", [])
    reply_text = state.get("reply_text", "")

    # 检查 mutation_logs 是否有有效数据
    if mutation_logs:
        for log in mutation_logs:
            if not log.get("event_id") or not log.get("op_type"):
                logger.warning("[ResultValidator] 发现无效 mutation_log: %s", log)
                return {
                    "validation_passed": False,
                    "validation_error": "发现无效的操作日志",
                    "reply_text": "操作执行过程中出现内部错误，请重试。",
                }

    # 检查回复是否为空
    if not reply_text and not mutation_logs:
        return {
            "validation_passed": False,
            "validation_error": "执行结果为空",
            "reply_text": "操作已完成，但未能生成响应。",
        }

    return {
        "validation_passed": True,
        "validation_error": None,
    }


def route_after_validation(state: ExtendedGraphState) -> Literal["pass", "fail"]:
    """【条件路由】校验通过 → 继续 / 失败 → post_process。"""
    if state.get("validation_passed", True):
        return "pass"
    return "fail"


# ==============================
# 节点 4c: StateUpdater (状态更新器)
# ==============================

def state_updater_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【状态更新器】递增 graph_version，发布事件。

    在每次成功执行后：
    1. graph_version += 1
    2. 为每个 mutation_log 发布 INVENTORY_CHANGED 事件
    3. 发布 EXECUTION_COMPLETED 事件（聚合元数据）
    4. 发布 SESSION_STATE_UPDATED 事件（版本变更通知）
    """
    current_version = state.get("graph_version", 0)
    new_version = current_version + 1
    mutation_logs = state.get("mutation_logs", [])

    # 5.5: 为每个 mutation_log 发布 INVENTORY_CHANGED 事件
    for log in mutation_logs:
        event = mutation_log_to_event(log, "state_updater")
        event_bus.publish(event)

    # 5.5: 发布 EXECUTION_COMPLETED 事件（含聚合元数据）
    op_types = list({log.get("op_type", "") for log in mutation_logs})
    event_bus.publish(SystemEvent(
        event_type=EventType.EXECUTION_COMPLETED,
        scope="SESSION",
        source_node="state_updater",
        payload={
            "mutation_count": len(mutation_logs),
            "intent": state.get("intent", ""),
            "op_types": op_types,
        },
    ))

    # 5.5: 发布 SESSION_STATE_UPDATED 事件（graph_version 递增）
    event_bus.publish(SystemEvent(
        event_type=EventType.SESSION_STATE_UPDATED,
        scope="SESSION",
        source_node="state_updater",
        payload={
            "graph_version": new_version,
            "mutation_count": len(mutation_logs),
        },
    ))

    logger.info("[StateUpdater] graph_version: %d → %d (mutation_logs=%d)",
                current_version, new_version, len(mutation_logs))

    return {
        "graph_version": new_version,
        "state_updated": True,
    }


# ==============================
# Phase 6 节点: Checkpoint (检查点)
# ==============================


def checkpoint_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【检查点】在成功执行后持久化状态快照。

    在 state_updater 之后调用，保存当前执行状态到 checkpoints 表。
    包含 mutation_logs 摘要、graph_version、intent 等关键状态。
    """
    graph_version = state.get("graph_version", 0)
    mutation_logs = state.get("mutation_logs", [])
    intent = state.get("intent", "")
    reply_text = state.get("reply_text", "")

    # 仅在 graph_version > 0 且有执行结果时保存检查点
    if graph_version > 0:
        try:
            from app.db.sqlite import connect

            checkpoint_id = f"ckpt_{uuid4().hex[:12]}"
            snapshot = {
                "intent": intent,
                "graph_version": graph_version,
                "mutation_log_count": len(mutation_logs),
                "reply_text_preview": reply_text[:100],
                "op_types": list({log.get("op_type", "") for log in mutation_logs}),
                "interaction_mode": state.get("interaction_mode", "normal"),
                "has_pending_operation": state.get("pending_operation") is not None,
            }
            with connect() as conn:
                save_checkpoint(
                    conn=conn,
                    checkpoint_id=checkpoint_id,
                    session_id="default_session",
                    graph_version=graph_version,
                    node_name="checkpoint_node",
                    state_snapshot=snapshot,
                )
            logger.info(
                "[Checkpoint] 已保存检查点 %s (version=%d logs=%d)",
                checkpoint_id, graph_version, len(mutation_logs),
            )
            return {"_last_checkpoint_id": checkpoint_id}
        except Exception:
            logger.exception("[Checkpoint] 保存检查点失败")

    return {}


# ==============================
# Phase 6 节点: TaskEvaluator (任务评估器)
# ==============================


# 评估结果字面量
TASK_CONTINUE = "continue"
TASK_DONE = "done"
TASK_SUSPEND = "suspend"


def task_evaluator_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【任务评估器】动态评估执行结果，决定下一步路由。

    根据执行状态返回:
    - CONTINUE: 有更多动作待执行 → 返回 Planner/重规划
    - DONE: 所有执行完成 → 进入 ResponseGenerator
    - SUSPEND: 需要用户确认 → 挂起

    当前实现简单判定: 只要有 mutation_logs 就标记 DONE，
    否则标记 SUSPEND（无实质变更时挂起）。
    """
    mutation_logs = state.get("mutation_logs", [])
    interaction_mode = state.get("interaction_mode", "normal")
    errors = state.get("errors", [])
    is_blocked = state.get("is_blocked", False)

    # 被策略拦截 → 对话已结束
    if is_blocked:
        return {"_task_result": TASK_DONE}

    # 有错误且无有效日志 → 挂起
    if errors and not mutation_logs:
        logger.info("[TaskEvaluator] 执行有错误且无变更 -> SUSPEND")
        return {"_task_result": TASK_SUSPEND}

    # 有 mutation_logs → 执行成功
    if mutation_logs:
        logger.info(
            "[TaskEvaluator] 执行完成 (%d logs) -> DONE",
            len(mutation_logs),
        )
        return {"_task_result": TASK_DONE}

    # 仍在 pending_selection 模式 → 等待用户确认
    if interaction_mode == "pending_selection":
        return {"_task_result": TASK_SUSPEND}

    # 默认: 简单查询或无变更 → DONE
    logger.info("[TaskEvaluator] 无变更 -> DONE")
    return {"_task_result": TASK_DONE}


def route_after_evaluator(state: ExtendedGraphState) -> Literal["continue", "done", "suspend"]:
    """【条件路由】根据 TaskEvaluator 结果分流。"""
    task_result = state.get("_task_result", TASK_DONE)
    if task_result == TASK_CONTINUE:
        return "continue"
    if task_result == TASK_SUSPEND:
        return "suspend"
    return "done"


# ==============================
# Phase 7 节点: Planner (规划器)
# ==============================


def planner_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【规划器】将 Intent + Entities 分解为 AgentAction 队列。

    调用 plan_actions() 生成动作列表，推入 workspace.action_queue。
    """
    intent = state.get("intent", "")
    entities = state.get("extracted_entities", {})
    graph_version = state.get("graph_version", 0)

    actions = plan_actions(
        intent=intent,
        entities=entities,
        session_id="default_session",
        graph_version=graph_version,
    )

    logger.info("[Planner] 生成了 %d 个动作: intent=%s", len(actions), intent)

    return {
        "current_action": actions[0] if actions else None,
        "action_queue": actions,
    }


# ==============================
# Phase 7 节点: ActionQueue (动作队列)
# ==============================


def action_queue_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【动作队列】从 FIFO 队列取出下一个 AgentAction。

    如果队列为空，标记 _queue_empty 以路由到 post_process。
    """
    action_queue = state.get("action_queue", [])
    current_action = state.get("current_action")

    # 如果已有 current_action 且未执行完成，保持
    if current_action:
        return {"_queue_empty": False}

    if not action_queue:
        logger.info("[ActionQueue] 队列为空")
        return {"_queue_empty": True, "current_action": None}

    # FIFO: 取出第一个
    next_action = action_queue[0]
    remaining = action_queue[1:]

    logger.info(
        "[ActionQueue] 出队: %s/%s (剩余 %d 个)",
        next_action.capability, next_action.tool_name, len(remaining),
    )

    return {
        "current_action": next_action,
        "action_queue": remaining,
        "_queue_empty": False,
    }


def route_after_queue(state: ExtendedGraphState) -> Literal["has_action", "empty"]:
    """【条件路由】队列有动作 → 继续执行 / 队列为空 → 结束。"""
    if state.get("_queue_empty"):
        return "empty"
    return "has_action"


# ==============================
# Phase 7 节点: LoopGuard (循环守卫)
# ==============================


def loop_guard_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【循环守卫】检查执行深度，防止无限循环。

    从 budget_guard_node 中提取的深度检查逻辑。
    如果 loop_depth >= max_depth，标记熔断。
    """
    loop_depth = state.get("loop_depth", 0)
    max_depth = state.get("max_depth", 5)

    if loop_depth >= max_depth:
        logger.warning("[LoopGuard] 深度 %d 已达上限 %d -> 熔断", loop_depth, max_depth)
        return {
            "loop_exceeded": True,
            "reply_text": f"操作深度已到达上限({max_depth})，请简化操作后重试。",
        }

    # 递增深度
    return {
        "loop_exceeded": False,
        "loop_depth": loop_depth + 1,
    }


def route_after_loop_guard(state: ExtendedGraphState) -> Literal["continue", "halt"]:
    """【条件路由】深度正常 → 继续 / 超限 → 熔断。"""
    if state.get("loop_exceeded"):
        return "halt"
    return "continue"


# ==============================
# Phase 8 节点: ResponseGenerator (响应生成器)
# ==============================


def response_generator_node(state: ExtendedGraphState) -> Dict[str, Any]:
    """【响应生成器】纯无状态渲染层，收口所有输出。

    职责：
    1. 从 state 中提取 reply_text 和上下文
    2. 处理 current_context_item 释放逻辑（原 post_process 中的空间记忆锁）
    3. 将最终回复写入 final_response 结构
    """
    accumulated_logs = state.get("mutation_logs", [])
    current_context = state.get("current_context_item")
    reply_text = state.get("reply_text", "收到，管家已为您处理完毕。")

    # 上下文防御：如果当前聚焦物品被移除，释放空间记忆锁
    updated_context = current_context
    for log in accumulated_logs:
        if log["op_type"] in ("remove", "consume") and current_context:
            if log.get("target_instance_id") == current_context.get("id"):
                logger.info("[ResponseGenerator] 释放已移除物品的空间记忆锁")
                updated_context = None

    return {
        "reply_text": reply_text,
        "current_context_item": updated_context,
        "final_response": {
            "reply_text": reply_text,
            "intent": state.get("intent", ""),
            "has_mutations": len(accumulated_logs) > 0,
            "interaction_mode": state.get("interaction_mode", "normal"),
        },
    }


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
    req_count = 1.0
    patch_data = entities.get("patch") or {}
    if "deductCount" in patch_data:
        try:
            req_count = float(patch_data["deductCount"])
        except (ValueError, TypeError):
            req_count = 1.0

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
            "interaction_mode": "pending_selection",
            "pending_item_selection": [_build_candidate_entries([target_item])[0]],
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
    cancel_keywords = {"取消", "退出", "不选了", "算了", "不要了"}
    if any(kw in text for kw in cancel_keywords):
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "reply_text": "已取消选择，有什么其他需要帮忙的吗？",
        }

    # 全部选择
    if text in ("全部", "所有", "全选"):
        if not selection:
            return {"reply_text": "没有可操作的物品。", "interaction_mode": "normal"}
        item_ids = [s.get("id") for s in selection if s.get("id")]

        op_type = pending_op.type if pending_op else "remove"
        patch = pending_op.patch if pending_op else {}

        # 根据原意图分流，保留原有的 operation 语义
        if op_type.startswith("update_"):
            return {
                "interaction_mode": "normal",
                "pending_item_selection": [],
                "pending_operation": None,
                "confirmed_item_ids": item_ids,
                "confirmed_patch": patch,
                "reply_text": _build_multi_update_reply(selection, op_type, patch),
            }
        if op_type == "consume":
            total_deduct = patch.get("deductCount")
            allocation = _build_multi_consume_allocation(selection, total_deduct)
            return {
                "interaction_mode": "normal",
                "pending_item_selection": [],
                "pending_operation": PendingOperation(
                    type="consume",
                    target_sku_title=pending_op.target_sku_title if pending_op else "",
                    patch={"deductCounts": allocation},
                    source_batch_ids=item_ids,
                ),
                "confirmed_item_ids": item_ids,
                "reply_text": _build_multi_consume_reply(selection, allocation),
            }
        # remove 默认
        return {
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "confirmed_item_ids": item_ids,
            "reply_text": _build_multi_remove_reply(selection),
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

    # --- 单选（取消 text.isdigit() 限制，完全以 valid_indices 解析结果为准） ---
    if len(valid_indices) == 1:
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
    """【统一出口】轻量透传 — 已迁移到 response_generator_node。"""
    return {
        "reply_text": state.get("reply_text", "收到，管家已为您处理完毕。"),
        "current_context_item": state.get("current_context_item"),
    }


# ==============================
# 图构建
# ==============================


# ==============================
# 事件消费者（EventBus 订阅者）
# ==============================

def _on_inventory_changed(event: SystemEvent) -> None:
    """【库存变更消费者】记录库存变更审计日志。

    职责：记录每次库存变更操作到审计日志。
    不修改 graph state — 只执行日志记录副作用。
    """
    logger.info(
        "[EventBus] 库存变更: %s %s x%s (target=%s)",
        event.payload.get("op_type", "?"),
        event.payload.get("sku_title", "?"),
        event.payload.get("delta", 0),
        event.payload.get("target_instance_id", "?"),
    )


def _on_execution_completed(event: SystemEvent) -> None:
    """【执行完成消费者】记录执行摘要。

    职责：记录本次图执行的变更摘要（mutation 数量、操作类型）。
    原 post_process_node 中的 mutation_logs 日志已移至此。
    不修改 graph state — 只执行日志记录副作用。
    """
    mutation_count = event.payload.get("mutation_count", 0)
    op_types = event.payload.get("op_types", [])
    intent = event.payload.get("intent", "")
    logger.info(
        "[EventBus] 执行完成: intent=%s mutation_count=%d op_types=%s",
        intent, mutation_count, op_types,
    )


def _on_session_updated(event: SystemEvent) -> None:
    """【会话更新消费者】记录 graph_version 变更。

    职责：记录版本变更事件，为后续审计追踪提供依据。
    不修改 graph state — 只执行日志记录副作用。
    """
    gv = event.payload.get("graph_version", 0)
    mc = event.payload.get("mutation_count", 0)
    logger.info(
        "[EventBus] Session version → %d (mutation_count=%d)",
        gv, mc,
    )


def _register_event_consumers() -> None:
    """注册所有事件消费者到 EventBus。

    在 build_squirrel_graph() 中调用，确保消费者在图编译前就位。
    """
    event_bus.subscribe(
        EventType.INVENTORY_CHANGED, "SESSION", _on_inventory_changed
    )
    event_bus.subscribe(
        EventType.EXECUTION_COMPLETED, "SESSION", _on_execution_completed
    )
    event_bus.subscribe(
        EventType.SESSION_STATE_UPDATED, "SESSION", _on_session_updated
    )
    logger.info("[EventBus] 已注册 3 个事件消费者")

def build_squirrel_graph():
    """构建新架构 LangGraph — 包含重入路由、指代消解、目标管理、快照管理。"""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(ExtendedGraphState)

    # 新增节点
    graph.add_node("re_entry_router", re_entry_router_node)
    graph.add_node("reference_resolver", reference_resolver_node)
    graph.add_node("goal_manager", goal_manager_node)
    graph.add_node("snapshot_store", snapshot_store_node)

    # 控制层节点
    graph.add_node("parameter_resolver", parameter_resolver_node)
    graph.add_node("policy_engine", policy_engine_node)
    graph.add_node("pre_execution_checker", pre_execution_checker_node)
    graph.add_node("budget_guard", budget_guard_node)
    graph.add_node("consistency_checker", consistency_checker_node)
    graph.add_node("capability_router", capability_router_node)

    # Phase 4 执行节点
    graph.add_node("tool_executor", tool_executor_node)
    graph.add_node("result_validator", result_validator_node)
    graph.add_node("state_updater", state_updater_node)

    # Phase 6 节点
    graph.add_node("checkpoint_node", checkpoint_node)
    graph.add_node("task_evaluator", task_evaluator_node)

    # Phase 7 节点
    graph.add_node("planner_node", planner_node)
    graph.add_node("action_queue_node", action_queue_node)
    graph.add_node("loop_guard_node", loop_guard_node)

    # Phase 8 节点
    graph.add_node("response_generator", response_generator_node)

    # 原有节点
    graph.add_node("input_router", multimodal_identity_router_node)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("confirm_subgraph_handler", confirm_subgraph_handler_node)
    graph.add_node("mutation_executor", mutation_executor_node)
    graph.add_node("query_handler", query_handler_node)
    graph.add_node("post_process", post_process_node)

    # START → re_entry_router（先检查是否存在挂起快照）
    graph.add_edge(START, "re_entry_router")

    # re_entry_router → reference_resolver (NEW) / snapshot_store (RESUME)
    graph.add_conditional_edges(
        "re_entry_router",
        route_after_reentry,
        {
            "resume": "snapshot_store",
            "new": "reference_resolver",
        },
    )

    # reference_resolver → goal_manager → input_router
    graph.add_edge("reference_resolver", "goal_manager")
    graph.add_edge("goal_manager", "input_router")

    # snapshot_store → response_generator (挂起快照后直接输出，下次从 START 由 re_entry_router 恢复)
    graph.add_edge("snapshot_store", "response_generator")

    # input_router → confirm_subgraph_handler / intent_classifier / post_process
    graph.add_conditional_edges(
        "input_router",
        route_after_input,
        {
            "go_to_confirm_handler": "confirm_subgraph_handler",
            "go_to_intent_classifier": "intent_classifier",
            "end_early": "response_generator",
        },
    )

    # intent_classifier → 控制层入口（parameter_resolver）
    graph.add_edge("intent_classifier", "parameter_resolver")

    # 控制层流水线
    graph.add_conditional_edges(
        "parameter_resolver",
        route_after_parameter_resolve,
        {
            "ready": "policy_engine",
            "missing": "snapshot_store",  # 参数缺失 → 挂起
        },
    )
    graph.add_conditional_edges(
        "policy_engine",
        route_after_policy,
        {
            "ready": "pre_execution_checker",
            "blocked": "snapshot_store",  # 被策略拦截 → 挂起快照（图中设计）
        },
    )
    graph.add_conditional_edges(
        "pre_execution_checker",
        route_after_pre_execution,
        {
            "ready": "budget_guard",
            "invalid": "snapshot_store",  # 无效操作 → 挂起快照（图中设计）
        },
    )
    graph.add_conditional_edges(
        "budget_guard",
        route_after_budget,
        {
            "ready": "consistency_checker",
            "exceeded": "snapshot_store",  # 预算超限 → 挂起
        },
    )
    graph.add_conditional_edges(
        "consistency_checker",
        route_after_consistency,
        {
            "ready": "capability_router",
            "inconsistent": "response_generator",  # 不一致 → 退回
        },
    )

    # capability_router → loop_guard_node (先做熔断检查再规划，与 mermaid-diagram 一致)
    graph.add_conditional_edges(
        "capability_router",
        route_after_capability,
        {
            "mutation": "loop_guard_node",
            "query": "query_handler",
        },
    )

    # loop_guard_node → planner_node (深度正常才规划) / response_generator (熔断)
    graph.add_conditional_edges(
        "loop_guard_node",
        route_after_loop_guard,
        {
            "continue": "planner_node",
            "halt": "response_generator",
        },
    )

    # planner_node → action_queue_node
    graph.add_edge("planner_node", "action_queue_node")

    # action_queue_node → tool_executor (有动作) / response_generator (空)
    graph.add_conditional_edges(
        "action_queue_node",
        route_after_queue,
        {
            "has_action": "tool_executor",
            "empty": "response_generator",
        },
    )

    # confirm_subgraph_handler → mutation_executor / post_process
    graph.add_conditional_edges(
        "confirm_subgraph_handler",
        route_after_confirm,
        {
            "success": "mutation_executor",
            "cancel": "response_generator",
        },
    )

    # mutation_executor → tool_executor
    graph.add_edge("mutation_executor", "tool_executor")

    # query_handler → response_generator (查询类不需要 ToolExecutor)
    graph.add_edge("query_handler", "response_generator")

    # confirm_subgraph_handler → mutation_executor (success) / post_process (cancel)
    # 已有上面的条件边

    # ==============================
    # Phase 7 执行管道 (来自 planner_node/action_queue_node)
    # ==============================
    # tool_executor → result_validator → state_updater → checkpoint_node → task_evaluator
    # task_evaluator → (done: post_process, continue: planner_node, suspend: snapshot_store)

    # Phase 4 内部流水线: tool_executor → result_validator → state_updater
    graph.add_conditional_edges(
        "tool_executor",
        route_after_validation,
        {
            "pass": "state_updater",
            "fail": "response_generator",
        },
    )

    # Phase 6: state_updater → checkpoint_node → task_evaluator
    graph.add_edge("state_updater", "checkpoint_node")
    graph.add_edge("checkpoint_node", "task_evaluator")

    # task_evaluator → 分流（continue 路径经过 loop_guard_node 熔断检查，与 mermaid-diagram 一致）
    graph.add_conditional_edges(
        "task_evaluator",
        route_after_evaluator,
        {
            "continue": "loop_guard_node",    # 重规划→先经过 LoopGuard 熔断检查
            "done": "response_generator",         # 执行完成
            "suspend": "snapshot_store",    # 挂起
        },
    )

    # 汇聚到 post_process
    graph.add_edge("response_generator", "post_process")
    graph.add_edge("post_process", END)

    # 5.6: 在图编译前注册事件消费者
    event_bus.reset()  # 防止测试中重复订阅
    _register_event_consumers()

    return graph.compile()


# ==============================
# 适配函数：ExtendedGraphState → 旧 dict 格式
# ==============================

def extended_to_old_dict(state: ExtendedGraphState, inventory: list[Item] | None = None) -> dict:
    """将新图输出适配为 routes.py 期望的旧格式（含 chat_result + db_operations）。"""
    intent = state.get("intent", "chat") or "chat"
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


def _run_replay_mode(
    text: str,
    inventory: list[Item],
    current_user_id: str,
    current_user_name: str,
) -> dict:
    """REPLAY 模式：加载检查点快照，跳过意图解析直接回放。

    从检查点加载上次执行的状态快照，构建旧格式输出。
    """
    from app.services.replay import replay_engine

    # 加载检查点
    checkpoints = replay_engine.load_checkpoints(limit=1)
    if not checkpoints:
        logger.warning("[REPLAY] 没有找到检查点，返回空结果")
        return {
            "chat_result": ChatResult(intent="chat", replyText="没有找到可回放的执行记录。"),
            "db_operations": {"upsert_items": [], "delete_ids": [], "pending_add": [], "pending_consume": {}},
            "interaction_mode": "normal",
            "pending_item_selection": [],
            "pending_operation": None,
            "last_added_item": None,
            "current_context_item": None,
            "recipe_recommend": None,
        }

    latest = checkpoints[0]
    snapshot = latest.get("state_snapshot", {})
    logger.info(
        "[REPLAY] 回放检查点 version=%d intent=%s",
        latest["graph_version"], snapshot.get("intent"),
    )

    # 构建旧格式输出
    intent = snapshot.get("intent", "chat")
    reply_text = snapshot.get("reply_text_preview", f"[回放] 版本 {latest['graph_version']}")
    chat_result = ChatResult(intent=intent, replyText=reply_text)

    return {
        "chat_result": chat_result,
        "db_operations": {"upsert_items": [], "delete_ids": [], "pending_add": [], "pending_consume": {}},
        "interaction_mode": "normal",
        "pending_item_selection": [],
        "pending_operation": None,
        "last_added_item": None,
        "current_context_item": None,
        "recipe_recommend": None,
    }


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
    execution_mode: str = "NEW",
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

    # 6.5: REPLAY 模式 — 加载检查点快照覆盖初始状态
    if execution_mode == "REPLAY":
        return _run_replay_mode(
            text=text,
            inventory=inventory or [],
            current_user_id=current_user_id,
            current_user_name=current_user_name,
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