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
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

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


class ExtendedGraphState(TypedDict, total=False):
    """下一代多模态家庭资产 Agent 的全局流转状态 (Graph State)

    total=False 允许额外的内部辅助字段（如 _inventory、_last_added_item）在图中传递。
    这是兼容层，保持与旧版 graph.py 的接口一致。
    """

    # ================== 入口输入层 ==================
    raw_text_input: str
    """当前轮次用户输入的原始文本(或语音转文字结果)"""

    image_payloads: List[str]
    """多模态输入：当前轮次上传的图片Base64列表(支持小票、条码、快照)"""

    current_user: UserContext
    """通过网关/多账号鉴权注入的当前操作人身份上下文"""

    # ================== 智能决策层 ==================
    intent: str
    """经 Intent Classifier 判定后的核心意图标签"""

    extracted_entities: Dict[str, Any]
    """从输入中抽取出的时空实体(如提及的数量、指定的地点别名、开封状态等)"""

    # ================== 跨轮交互与状态锁 (State Lock) ==================
    interaction_mode: str
    """当前的交互模式: normal(正常聊天), pending_selection(等待选择/确认冲突)"""

    current_context_item: Optional[Dict[str, Any]]
    """
    【核心重构】当前对话聚焦的物品时空上下文（消灭记忆错乱错位）
    结构: {"instance_id": "xxx", "title": "全麦面包", "location": "厨房二级柜"}
    """

    pending_item_selection: List[Dict[str, Any]]
    """发生冲突或多候选匹配时，推送给用户供选择的 Instance 候选集"""

    pending_operation: Optional[PendingOperation]
    """当 interaction_mode 为 pending 时，被锁定的、等待用户说'确认/1'后执行的底层事务"""

    # ================== 输出与同步层 ==================
    reply_text: str
    """Agent 最终决定向当前用户输出的高情商文本回复"""

    recipe_recommendation: Optional[Dict[str, Any]]
    """如果触发了菜谱生成，存放结构化菜谱推荐结果的容器"""

    # 采用 Reducer 的增量日志流，用于追踪原子操作，方便 Post_Process 节点进行多路异步同步
    mutation_logs: Annotated[List[Dict[str, Any]], merge_audit_logs]
    """本次图流转中真正发生变更的数据库写操作日志(用于安全审计、撤销及异步同步向量库)"""

    # ================== 内部辅助字段 ==================
    inventory: List  # 当前库存快照（Item 列表）
    last_added_item: Optional[Dict[str, Any]]  # 最近一次新增成功的物品
    user_preference: str  # 用户饮食偏好
    reminder_time: str  # 提醒时间
    confirmed_item_id: Optional[str]  # 已确认的单选物品 ID
    confirmed_item_ids: List[str]  # 已确认的多选物品 ID 列表
    confirmed_patch: Optional[Dict[str, Any]]  # 已确认的补丁
    pending_add_items: List[Dict[str, Any]]  # 待新增的物品列表（用于适配层）

    # ================== 控制层字段（Phase 3） ==================
    missing_parameters: List[str]  # 参数解析器检测到的缺失参数
    is_blocked: bool  # 策略引擎是否拦截了操作
    is_invalid: bool  # 预执行检查器是否判定操作无效
    is_inconsistent: bool  # 一致性检查器检测到冲突
    needs_correction: bool  # 是否需要自动修正
    budget_exceeded: bool  # 预算是否超出
    policy_violations: List[Dict[str, Any]]  # 触发的策略规则列表
    budget_checks: List[str]  # 预算检查记录
    consistency_issues: List[str]  # 一致性检查记录
    pre_execution_checks: List[str]  # 预执行检查记录
    capability: str  # 路由到的能力域名称
    current_action: Any  # 当前执行的 AgentAction


# ==========================================
# 8. 状态转换函数
# ==========================================


def agent_to_extended(agent_state: AgentGraphState) -> ExtendedGraphState:
    """将 AgentGraphState 转换为 ExtendedGraphState (TypedDict)。

    用于将新架构的状态向下兼容到旧版 LangGraph 节点。
    """
    memory = agent_state.memory
    workspace = agent_state.workspace
    snapshot = agent_state.snapshot

    # 从 workspace.scratchpad 中提取旧版字段
    scratchpad = workspace.scratchpad

    return {
        "raw_text_input": agent_state.raw_user_input,
        "image_payloads": agent_state.normalized_request.get("image_payloads", []),
        "current_user": UserContext(
            user_id=memory.user_id,
            user_name=memory.household_profile.get("user_name", "主人"),
            role=memory.household_profile.get("role", "member"),
            current_zone=memory.household_profile.get("current_zone"),
        ),
        "intent": agent_state.normalized_request.get("intent", ""),
        "extracted_entities": agent_state.normalized_request.get("extracted_entities", {}),
        "interaction_mode": scratchpad.get("interaction_mode", "normal"),
        "current_context_item": scratchpad.get("current_context_item"),
        "pending_item_selection": scratchpad.get("pending_item_selection", []),
        "pending_operation": scratchpad.get("pending_operation"),
        "reply_text": agent_state.final_response.get("reply_text", ""),
        "recipe_recommendation": agent_state.final_response.get("recipe_recommendation"),
        "mutation_logs": scratchpad.get("mutation_logs", []),
        "inventory": scratchpad.get("inventory", []),
        "last_added_item": scratchpad.get("last_added_item"),
        "user_preference": memory.user_preferences.get("diet", "无特殊要求"),
        "reminder_time": memory.user_preferences.get("reminder_time", ""),
        "confirmed_item_id": scratchpad.get("confirmed_item_id"),
        "confirmed_item_ids": scratchpad.get("confirmed_item_ids", []),
        "confirmed_patch": scratchpad.get("confirmed_patch"),
        "pending_add_items": scratchpad.get("pending_add_items", []),
    }


def extended_to_agent(
    ext_state: ExtendedGraphState,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> AgentGraphState:
    """将 ExtendedGraphState (TypedDict) 转换为 AgentGraphState。

    用于将旧版图形状态迁移到新架构状态。
    """
    current_user = ext_state.get("current_user") or UserContext(
        user_id="default_user",
        user_name="主人",
        role="member",
    )

    memory = MemoryStoreState(
        user_id=current_user.user_id,
        household_profile={
            "user_name": current_user.user_name,
            "role": current_user.role,
            "current_zone": current_user.current_zone,
        },
        user_preferences={
            "diet": ext_state.get("user_preference", "无特殊要求"),
            "reminder_time": ext_state.get("reminder_time", ""),
        },
    )

    scratchpad: Dict[str, Any] = {
        "interaction_mode": ext_state.get("interaction_mode", "normal"),
        "current_context_item": ext_state.get("current_context_item"),
        "pending_item_selection": ext_state.get("pending_item_selection", []),
        "pending_operation": ext_state.get("pending_operation"),
        "mutation_logs": ext_state.get("mutation_logs", []),
        "inventory": ext_state.get("inventory", []),
        "last_added_item": ext_state.get("last_added_item"),
        "confirmed_item_id": ext_state.get("confirmed_item_id"),
        "confirmed_item_ids": ext_state.get("confirmed_item_ids", []),
        "confirmed_patch": ext_state.get("confirmed_patch"),
        "pending_add_items": ext_state.get("pending_add_items", []),
    }

    return AgentGraphState(
        session_id=session_id or f"sess_{uuid.uuid4().hex[:12]}",
        trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
        execution_mode="NEW",
        raw_user_input=ext_state.get("raw_text_input", ""),
        normalized_request={
            "image_payloads": ext_state.get("image_payloads", []),
            "intent": ext_state.get("intent", ""),
            "extracted_entities": ext_state.get("extracted_entities", {}),
        },
        final_response={
            "reply_text": ext_state.get("reply_text", ""),
            "recipe_recommendation": ext_state.get("recipe_recommendation"),
        },
        memory=memory,
        workspace=WorkspaceStoreState(
            scratchpad=scratchpad,
        ),
    )


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
