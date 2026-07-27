"""Policy and control-flow nodes."""

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
    parse_lightning_text,
    parse_multi_selection,
)
from app.services.spatial_service import spatial_service
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)
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

    elif intent == "update_remark":
        if not target:
            missing.append("target")
        if not patch.get("remarkAppend") and patch.get("remark") is None:
            missing.append("remark")

    # 如果有缺失参数，设置回复文本
    if missing:
        missing_names = {
            "target_items": "物品名称或数量",
            "target": "物品名称",
            "location": "目标位置",
            "expire_date": "保质期日期",
            "remark": "备注内容",
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
    if intent in ("consume", "remove", "update_location", "update_expiry", "update_remark") and target:
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
        "update_remark": "inventory",
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
    medium_risk_intents = {"update_location", "update_expiry", "update_remark", "update_remaining"}

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
    if intent in ("add", "consume", "remove", "update_location", "update_expiry", "update_remark", "update_remaining"):
        return "mutation"
    return "query"


