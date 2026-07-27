"""新架构领域模型与 Graph State 定义。

本模块定义 LangGraph 重构后的核心数据结构：
- ActionStatus, AgentAction: 动作幂等锁基础原子结构
- SystemEvent: 结构化事件载荷
- MemoryStoreState, WorkspaceStoreState, SnapshotStoreState: 执行上下文三驾马车
- AgentGraphState: 集成执行语义层的全局图状态
- UserContext: 多家庭成员身份上下文
- ItemInstance: 物品仓储实例 (Instance) —— 每个单品有独立 ID
- PendingOperation: 被挂起的待确认事务声明
- merge_audit_logs: 自定义 Reducer，用于增量合并审计日志
- ExtendedGraphState: 兼容层，保留旧版 TypedDict 状态定义
- 状态转换函数: agent_to_extended(), extended_to_agent()
"""

from __future__ import annotations

import json
import operator
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import add_messages
from pydantic import BaseModel, Field


# ==========================================
# 1. 基础原子结构（带幂等锁）
# ==========================================


class ActionStatus(str, Enum):
    """动作执行状态枚举"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class AgentAction(BaseModel):
    """可执行动作单元，携带幂等锁"""
    action_id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:12]}")
    idempotency_key: str = Field(
        ..., description="动作幂等锁，格式: {session_id}:{graph_version}:{action_id}"
    )
    capability: str = Field(..., description="路由目标能力域")
    tool_name: str = Field(..., description="核心工具名称")
    arguments: Dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.PENDING
    risk_level: str = Field(default="LOW", description="风险等级: LOW / MEDIUM / HIGH / CRITICAL")


# ==========================================
# 2. 结构化事件载荷
# ==========================================


class SystemEvent(BaseModel):
    """系统事件，用于 EventBus 精准分发"""
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_type: str = Field(..., description="事件类型，如 InventoryChanged, ThresholdTriggered")
    scope: Literal["GLOBAL", "SESSION", "LOCAL"] = "SESSION"
    source_node: str = Field(..., description="发出事件的节点名称")
    priority: int = Field(default=1, description="消费优先级，数值越小优先级越高")
    payload: Dict[str, Any] = Field(default_factory=dict)
class EventType:
    """事件类型常量 — 用于 EventBus 精准路由。

    常量:
        INVENTORY_CHANGED: 库存变更（add/consume/remove/update）
        EXECUTION_COMPLETED: 执行完成
        SESSION_STATE_UPDATED: 会话状态更新（graph_version 递增时）
    """
    INVENTORY_CHANGED = "InventoryChanged"
    EXECUTION_COMPLETED = "ExecutionCompleted"
    SESSION_STATE_UPDATED = "SessionStateUpdated"


# ==========================================
# 3. 执行上下文三驾马车
# ==========================================


class MemoryStoreState(BaseModel):
    """长期记忆与用户画像（跨会话持久化）"""
    user_id: str = "default_user"
    household_profile: Dict[str, Any] = Field(default_factory=dict)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceStoreState(BaseModel):
    """当前会话临时变量与工作区"""
    current_plan: List[str] = Field(default_factory=list)
    action_queue: List[AgentAction] = Field(default_factory=list)
    executed_actions: List[AgentAction] = Field(default_factory=list)
    tool_outputs: Dict[str, Any] = Field(default_factory=dict)
    scratchpad: Dict[str, Any] = Field(default_factory=dict)


class SnapshotStoreState(BaseModel):
    """栈帧级快照：完全对齐 Execution Frame Semantics"""
    is_suspended: bool = False
    snapshot_id: str = Field(default="", description="快照唯一标识")
    graph_version: int = Field(default=0, description="快照时的图执行版本号")
    suspension_reason: Optional[str] = Field(default=None, description="挂起原因: CLARIFICATION / CONFIRMATION")

    # 发生挂起时封存的现场快照
    action_queue_snapshot: List[AgentAction] = Field(default_factory=list)
    workspace_snapshot: Dict[str, Any] = Field(default_factory=dict)
    loop_depth_snapshot: int = 0

    missing_parameters: List[str] = Field(default_factory=list)
    blocked_action_id: Optional[str] = None
    user_choice_options: List[str] = Field(default_factory=list)


# ==========================================
# 4. 全局图状态（集成执行语义层）
# ==========================================


class AgentGraphState(BaseModel):
    """工业级 Graph State，集成 Execution Semantics Layer

    支持四种执行模式：
    - NEW: 全新任务，走完整意图解析与全局规划
    - RESUME: 重入任务，跳过意图分类，直接解冻快照继续执行
    - SUSPENDED: 挂起任务，执行链被成功截断
    - REPLAY: 系统容灾或审计模式，基于 Checkpoint 重跑
    """
    # 执行语义层
    session_id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:12]}")
    execution_mode: Literal["NEW", "RESUME", "SUSPENDED", "REPLAY"] = "NEW"
    graph_version: int = Field(default=0, description="单调递增的逻辑时钟/状态版本")

    # I/O 边界
    raw_user_input: str = ""
    normalized_request: Dict[str, Any] = Field(default_factory=dict)
    final_response: Dict[str, Any] = Field(default_factory=dict)

    # 上下文域
    memory: MemoryStoreState = Field(default_factory=MemoryStoreState)
    workspace: WorkspaceStoreState = Field(default_factory=WorkspaceStoreState)
    snapshot: SnapshotStoreState = Field(default_factory=SnapshotStoreState)

    # 熔断与容错
    loop_depth: int = Field(default=0)
    max_depth: int = Field(default=5)
    errors: List[Dict[str, Any]] = Field(default_factory=list)


# ==========================================
# 5. 基础领域模型 (Domain Models)
# ==========================================


class UserContext(BaseModel):
    """多家庭成员身份上下文"""
    user_id: str = Field(..., description="用户唯一ID")
    user_name: str = Field(..., description="用户昵称/称呼(如:老公、老婆)")
    role: str = Field("member", description="角色/权限级别: admin(家长), member(成员), guest(访客)")
    current_zone: Optional[str] = Field(None, description="当前用户所在的物理区域(结合室内定位时使用)")


class ItemInstance(BaseModel):
    """物品仓储实例表 (Instance) —— 真正去解决'周一和周二牛奶'的实体"""
    id: str = Field(..., description="每个单品独立的身份证ID")
    sku_id: str = Field(..., description="指向SKU定义表的ID")
    title: str = Field(..., description="物品名称别名/冗余")

    # 空间拓扑关联
    slot_id: str = Field(..., description="叶子微空间ID(对应Slot)")
    space_name: str = Field(..., description="宏观区域名(如:厨房)")
    location: str = Field(..., description="具体位置描绘(如:冷藏层第二格)")

    # 数量与状态
    count: float = Field(default=1.0, description="当前实例的数量")
    unit: str = Field(default="件", description="单位")
    remaining_pct: int = Field(default=100, description="剩余容量百分比(0-100)")

    # 时间生命周期管理
    official_expiry_date: Optional[datetime] = Field(None, description="官方外包装保质期")
    opened_date: Optional[datetime] = Field(None, description="开封时间")
    pao_days: Optional[int] = Field(None, description="PAO相对开封有效天数")
    final_expiry_date: Optional[datetime] = Field(None, description="通过公式算出的最终截止日")

    # 协同与审计日志
    last_modified_by: str = Field(..., description="最后一次移动/消耗该物品的用户ID")
    last_modified_at: datetime = Field(default_factory=datetime.now, description="最后修改时间")


class PendingOperation(BaseModel):
    """被挂起的待确认事务声明"""
    type: str = Field(..., description="操作类型: add, consume, remove, update")
    target_sku_title: str = Field(..., description="用户口语提及的目标物品")
    patch: Dict[str, Any] = Field(default_factory=dict, description="待修改的属性字典")
    consume_all: bool = Field(default=False, description="是否一键清空/全部消耗")
    source_batch_ids: List[str] = Field(default_factory=list, description="涉及到的候选批次Instance_ID列表")


# ==========================================
# 6. 自定义 Reducer：用于 Annotated 增量日志
# ==========================================


def merge_audit_logs(old_logs: List[Dict[str, Any]], new_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """自定义Reducers：用于增量合并审计日志"""
    return old_logs + new_logs


# ==========================================
# 7. LangGraph 全局状态定义 (兼容层)
# ==========================================


# ============ 结构化子类型（消灭布尔爆炸）============
class ControlVerdict(TypedDict):
    status: Literal["pass", "blocked", "invalid", "inconsistent", "budget_exceeded"]
    violations: list[str]
    suspend_question: Optional[str]  # 如果需要反问用户

class TaskVerdict(TypedDict):
    decision: Literal["continue", "suspend", "done"]
    reason: str
    depth: int  # 当前循环深度

# ============ 主图 State（精简，只管层间通信）============
class MainGraphState(TypedDict, total=False):
    # --- 输入层 ---
    messages: Annotated[list, add_messages]  # ← State B 缺的，必须有
    raw_text_input: str
    image_payloads: list[str]               # ← 保留 State B 的多模态
    current_user: dict                       # ← 保留用户身份

    # --- 决策层 ---
    intent: str
    extracted_entities: dict
    current_context_item: Optional[dict]     # ← 保留 State B 的上下文聚焦

    # --- 控制层（结构化，非布尔）---
    control_verdict: ControlVerdict          # ← 替代 6 个布尔
    resolved_params: dict

    # --- 循环控制 ---
    task_verdict: TaskVerdict                # ← 替代分散的判断，含 depth

    # --- 交互状态机 ---
    interaction_mode: Literal["normal", "pending_selection", "pending_confirm"]
    pending_operation: Optional[dict]
    pending_item_selection: list[dict]

    # --- 输出层 ---
    reply_text: str
    recipe_recommendation: Optional[dict]

    # --- 审计（Reducer 增量追加）---
    mutation_logs: Annotated[list[dict], operator.add]  # ← 保留 State B 的审计

# ============ 子图 State（内部细节不泄漏）============
class InventorySubState(MainGraphState):
    inventory: list
    last_added_item: Optional[dict]
    confirmed_item_id: Optional[str]
    pending_add_items: list[dict]

class RecommendationSubState(MainGraphState):
    user_preference: str
    recipe_candidates: list[dict]


class ExtendedGraphState(MainGraphState, total=False):
    """Compatibility state used by the current Squirrel workflow.

    The graph is being migrated toward the smaller structured states above,
    but its nodes still exchange legacy execution and API-adapter fields.
    LangGraph requires every persisted channel to be declared explicitly.
    """

    current_user: UserContext
    pending_operation: Optional[PendingOperation]
    inventory: list[Any]
    last_added_item: Optional[dict[str, Any]]
    user_preference: str
    reminder_time: str
    confirmed_item_id: Optional[str]
    confirmed_item_ids: list[str]
    confirmed_patch: Optional[dict[str, Any]]
    pending_add_items: list[dict[str, Any]]

    missing_parameters: list[str]
    is_blocked: bool
    is_invalid: bool
    is_inconsistent: bool
    needs_correction: bool
    budget_exceeded: bool
    policy_violations: list[dict[str, Any]]
    budget_checks: list[str]
    consistency_issues: list[str]
    pre_execution_checks: list[str]
    capability: str

    current_action: Optional[AgentAction]
    action_queue: list[AgentAction]
    execution_results: list[dict[str, Any]]
    plan: list[AgentAction]
    loop_depth: int
    max_depth: int
    graph_version: int
    validation_passed: bool
    validation_error: Optional[str]
    idempotency_hit: bool

    _snapshot_was_restored: bool
    _goal_resolved: bool
    _goal_target: str


def agent_to_extended(agent_state: AgentGraphState) -> ExtendedGraphState:
    """Deprecated compatibility adapter retained for callers and tests."""
    return {}


def extended_to_agent(
    ext_state: ExtendedGraphState,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> AgentGraphState:
    """Deprecated compatibility adapter retained for callers and tests."""
    return AgentGraphState(
        session_id=session_id or f"sess_{uuid.uuid4().hex[:12]}",
        trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
    )


# ==========================================
# 9. 快照与幂等工具函数
# ==========================================


def create_snapshot(state: AgentGraphState, reason: str = "CLARIFICATION") -> SnapshotStoreState:
    """创建当前状态的栈帧快照（深拷贝现场）。

    Args:
        state: 当前 AgentGraphState
        reason: 挂起原因

    Returns:
        填充了现场快照的 SnapshotStoreState
    """
    return SnapshotStoreState(
        is_suspended=True,
        snapshot_id=f"snap_{uuid.uuid4().hex[:12]}",
        graph_version=state.graph_version,
        suspension_reason=reason,
        action_queue_snapshot=[action.model_copy(deep=True) for action in state.workspace.action_queue],
        workspace_snapshot=state.workspace.scratchpad.copy(),
        loop_depth_snapshot=state.loop_depth,
    )


def restore_snapshot(state: AgentGraphState, snapshot: SnapshotStoreState) -> AgentGraphState:
    """从快照恢复现场。

    Args:
        state: 当前 AgentGraphState
        snapshot: 要恢复的快照

    Returns:
        恢复后的 AgentGraphState（graph_version 递增）

    Raises:
        ValueError: 如果快照的 graph_version 与当前版本不匹配（状态漂移）
    """
    if snapshot.graph_version != state.graph_version:
        raise ValueError(
            f"版本冲突: 快照版本 {snapshot.graph_version} ≠ 当前版本 {state.graph_version}。"
            "可能发生了状态漂移，拒绝恢复。"
        )

    state.execution_mode = "RESUME"
    state.snapshot = snapshot
    state.workspace.action_queue = [action.model_copy(deep=True) for action in snapshot.action_queue_snapshot]
    state.workspace.scratchpad.update(snapshot.workspace_snapshot)
    state.loop_depth = snapshot.loop_depth_snapshot
    return state


def generate_idempotency_key(session_id: str, graph_version: int, tool_name: str, arguments: dict) -> str:
    """生成幂等锁 key。

    格式: {session_id}:{graph_version}:{tool_name}:{arguments_hash}
    """
    args_str = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    args_hash = uuid.uuid5(uuid.NAMESPACE_DNS, f"{session_id}:{graph_version}:{tool_name}:{args_str}")
    return f"{session_id}:{graph_version}:{tool_name}:{args_hash.hex[:16]}"


def version_conflict_check(current_version: int, snapshot_version: int) -> bool:
    """版本冲突检测。

    Returns:
        True 如果版本一致（无冲突），False 如果版本不一致（有冲突）
    """
    return current_version == snapshot_version

def mutation_log_to_event(log: dict, source_node: str) -> SystemEvent:
    """将 mutation_log 字典转换为 SystemEvent。

    mutation_log 结构:
        event_id: str — 操作唯一ID
        op_type: str — 操作类型 (add/consume/remove/update)
        target_instance_id: str — 目标物品实例ID
        sku_title: str — 物品名称
        delta: float — 数量变化
        patch: dict — 属性变更补丁

    映射规则:
        op_type → event_type 映射到 InventoryChanged
        payload 包含原始 log 的全部字段
    """
    event_type = EventType.INVENTORY_CHANGED
    return SystemEvent(
        event_id=f"evt_{log.get('event_id', uuid.uuid4().hex[:12])}",
        event_type=event_type,
        scope="SESSION",
        source_node=source_node,
        payload={
            "op_type": log.get("op_type", ""),
            "target_instance_id": log.get("target_instance_id", ""),
            "sku_title": log.get("sku_title", ""),
            "delta": log.get("delta", 0),
            "patch": log.get("patch"),
            "original_event_id": log.get("event_id"),
        },
    )
