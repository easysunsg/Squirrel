"""LangGraph topology, compatibility adapter, and public runner."""

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

from app.services.graph_control import *  # noqa: F403
from app.services.graph_execution import *  # noqa: F403
from app.services.graph_input import *  # noqa: F403
from app.services.graph_interaction import *  # noqa: F403
from app.services.graph_utils import _match_items_3tier

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
    graph.add_node("conflict_batch_resolver", conflict_batch_resolver_node)
    graph.add_node("confirm_subgraph_handler", confirm_subgraph_handler_node)
    graph.add_node("mutation_executor", mutation_executor_node)
    graph.add_node("query_handler", query_handler_node)
    graph.add_node("post_process", post_process_node)

    # START → re_entry_router（先检查是否存在挂起快照）
    graph.add_edge(START, "re_entry_router")

    # Resumed state must process the current input. Selections continue the
    # suspended operation; unrelated text starts a new request.
    graph.add_conditional_edges(
        "re_entry_router",
        route_after_reentry,
        {
            "resume": "input_router",
            "new": "input_router",
        },
    )

    # Entity-dependent context resolution must run after intent extraction.
    graph.add_edge("reference_resolver", "goal_manager")
    graph.add_edge("goal_manager", "parameter_resolver")

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

    # intent_classifier → reference_resolver → goal_manager → parameter_resolver
    graph.add_edge("intent_classifier", "reference_resolver")

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

    # Mutation requests resolve inventory conflicts before planning.
    graph.add_conditional_edges(
        "capability_router",
        route_after_capability,
        {
            "mutation": "conflict_batch_resolver",
            "query": "query_handler",
        },
    )

    graph.add_conditional_edges(
        "conflict_batch_resolver",
        route_after_resolver,
        {
            "execute": "loop_guard_node",
            "pending": "response_generator",
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

    # Confirmation execution already produces mutation logs; validate it
    # directly instead of executing the same operation a second time.
    graph.add_edge("mutation_executor", "result_validator")

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
    graph.add_edge("tool_executor", "result_validator")
    graph.add_conditional_edges(
        "result_validator",
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
            item_data = log.get("item_data", {})
            if item_data:
                item = Item.model_validate(item_data) if isinstance(item_data, dict) else item_data
                db_ops["upsert_items"].append(item)
            else:
                db_ops["upsert_items"].append(Item(title=sku_title, count=abs(delta) if delta else 1))

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

    # --- 构建 chat_result ---
    needs_confirm = interaction_mode in ("pending_selection", "pending_confirm") or bool(db_ops.get("pending_consume"))

    item_suggestion = None
    if interaction_mode == "pending_confirm" and pending_op and pending_op.type == "add":
        item_suggestion = {"items": pending_selection}

    chat_result = ChatResult(
        intent=intent,
        replyText=reply_text,
        needsConfirmation=needs_confirm,
        itemSuggestion=item_suggestion,
    )

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
            target_sku_title=pending_operation.get("target_sku_title") or pending_operation.get("target", ""),
            patch=pending_operation.get("patch", {}),
            consume_all=pending_operation.get("consume_all", pending_operation.get("consumeAll", False)),
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
        "interaction_mode": interaction_mode if interaction_mode in ("pending_selection", "pending_confirm") else "normal",
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
