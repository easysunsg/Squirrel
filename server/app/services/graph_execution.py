"""Planning, execution, validation, and checkpoint nodes."""

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
        "update_remark": "inventory",
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
    reply_text = (state.get("reply_text") or "").strip()
    if not reply_text:
        reply_text = "收到，管家已为您处理完毕。"

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


