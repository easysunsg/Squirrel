## 一、 顶配版工业级 Graph State 数据结构

引入了全局执行语义 `execution_mode`、动作幂等锁 `idempotency_key` 以及严格的栈帧版本快照机制：

```python
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field

# ==========================================
# 1. 基础原子结构（带幂等锁）
# ==========================================

class ActionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class AgentAction(BaseModel):
    action_id: str
    idempotency_key: str              # ⭐ 关键：动作幂等锁，格式通常为: {session_id}:{graph_version}:{action_id}
    capability: str                  # 路由目标
    tool_name: str                   # 核心工具
    arguments: Dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.PENDING
    risk_level: str = "LOW"

# ==========================================
# 2. 结构化事件载荷
# ==========================================

class SystemEvent(BaseModel):
    event_id: str
    event_type: str                  # 如 "InventoryChanged", "ThresholdTriggered"
    scope: Literal["GLOBAL", "SESSION", "LOCAL"]
    source_node: str                 # 哪个节点发出的事件
    priority: int = 1                # 消费优先级
    payload: Dict[str, Any] = Field(default_factory=dict)

# ==========================================
# 3. 执行上下文三驾马车（支持 Frame 快照）
# ==========================================

class MemoryStoreState(BaseModel):
    user_id: str
    household_profile: Dict[str, Any] = Field(default_factory=dict)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)

class WorkspaceStoreState(BaseModel):
    current_plan: List[str] = Field(default_factory=list)
    action_queue: List[AgentAction] = Field(default_factory=list)
    executed_actions: List[AgentAction] = Field(default_factory=list)
    tool_outputs: Dict[str, Any] = Field(default_factory=dict)
    scratchpad: Dict[str, Any] = Field(default_factory=dict)

class SnapshotStoreState(BaseModel):
    """⭐ 栈帧级快照：完全对齐 Execution Frame Semantics"""
    is_suspended: bool = False
    snapshot_id: str = ""             # 快照唯一标识
    graph_version: int = 0            # ⭐ 图当前的执行版本号，用于对齐
    suspension_reason: Optional[str] = None # 挂起原因 (CLARIFICATION / CONFIRMATION)
    
    # 发生挂起时封存的现场快照（隔离现场，防止污染）
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
    session_id: str
    trace_id: str
    
    # ⭐ 核心抽象：Execution Semantics Layer
    execution_mode: Literal["NEW", "RESUME", "SUSPENDED", "REPLAY"] = "NEW"
    graph_version: int = Field(default=0, description="单单调递增的逻辑时钟/状态版本")
    
    # I/O 边界
    raw_user_input: str = ""
    normalized_request: Dict[str, Any] = Field(default_factory=dict)
    final_response: Dict[str, Any] = Field(default_factory=dict)
    
    # 上下文域
    memory: MemoryStoreState
    workspace: WorkspaceStoreState
    snapshot: SnapshotStoreState
    
    # 熔断与容错
    loop_depth: int = Field(default=0)
    max_depth: int = Field(default=5)
    errors: List[Dict[str, Any]] = Field(default_factory=list)

```

---

## 二、 升级后的最终确定性图拓扑（Industrial Architecture）

我们在关键路径上植入了 **`ReEntryRouter`**、**`Execution Mode 控制逻辑`** 以及 **`EventRouter`**。

```mermaid
flowchart TD

User([User])

%% ==========================================
%% INPUT & COMPOSITE CONTEXT LAYER 
%% ==========================================
subgraph INPUT_LAYER [输入与重入分流层]
    NormalizeRequest[NormalizeRequest]
    
    ReEntryRouter{ReEntryRouter <br/><i>*判定新任务还是恢复现场</i>}
    
    subgraph CONTEXT_CONTAINER [Context Stores]
        SnapshotStore[(SnapshotStore <br/><i>*Execution Frames</i>)]
        WorkspaceStore[(WorkspaceStore <br/><i>*Scratchpad</i>)]
        MemoryStore[(MemoryStore <br/><i>*Profiles</i>)]
    end
    
    ReferenceResolver[ReferenceResolver]
    GoalManager[GoalManager]
    IntentClassifier[IntentClassifier]
end

%% ==========================================
%% BRAIN & GUARD LAYER
%% ==========================================
subgraph BRAIN_LLM [动态规划大脑]
    LoopGuard{LoopGuard <br/><i>*深度熔断计数器</i>}
    Planner[Planner <br/><i>*生成 Action & Idempotency Key</i>}
    ActionQueue[ActionQueue]
end

%% ==========================================
%% CONTROL & CHECK LAYER
%% ==========================================
subgraph CONTROL_LAYER [控制与拦截层]
    ParameterResolver[ParameterResolver]
    PolicyEngine[PolicyEngine]
    PreExecutionChecker{PreExecutionChecker <br/><i>*静态拦截与风控</i>}
    
    BudgetGuard[BudgetGuard]
    ConsistencyChecker[ConsistencyChecker]
    CapabilityRouter[CapabilityRouter]
end

%% ==========================================
%% CAPABILITIES & EXECUTION (With DB Unique Lock)
%% ==========================================
subgraph CAPABILITIES [能力域与确定性执行]
    InventoryCapability[InventoryCapability]
    ExpirationCapability[ExpirationCapability]
    RecommendationCapability[RecommendationCapability]
    BatchCapability[BatchCapability]
    HouseholdCapability[HouseholdCapability]
    
    ToolExecutor[ToolExecutor <br/><i>*DB Unique Lock 校验</i>]
    ResultValidator{ResultValidator}
    StateUpdater[StateUpdater <br/><i>*Graph Version 递增</i>]
    
    EventBus[EventBus]
    EventRouter[EventRouter <br/><i>*按 Type/Scope 精准路由</i>]
    
    Checkpoint[Checkpoint]
    TaskEvaluator{TaskEvaluator <br/><i>*动态评估器</i>}
end

%% ==========================================
%% OUTPUT LAYER (Pure Sink)
%% ==========================================
subgraph OUTPUT_LAYER [无状态渲染层]
    ResponseGenerator[ResponseGenerator <br/><i>*纯 UI 渲染</i>]
    Output([Response])
end

%% ==========================================
%% LOGICAL FLOW LINES
%% ==========================================

%% 1. 重入路由与现场恢复逻辑
User --> NormalizeRequest
NormalizeRequest --> ReEntryRouter

%% ReEntryRouter 逻辑分支
ReEntryRouter -->|检查存在活跃挂起快照| SnapshotStore
SnapshotStore -->|Thaw 恢复隔离现场 / mode=RESUME| WorkspaceStore
WorkspaceStore --> ReferenceResolver

ReEntryRouter -->|无挂起快照 / mode=NEW| ReferenceResolver
MemoryStore --> ReferenceResolver

ReferenceResolver --> GoalManager
GoalManager --> IntentClassifier

%% 2. 规划与深度熔断
IntentClassifier --> LoopGuard
LoopGuard -->|Depth OK| Planner
LoopGuard -->|Depth Exceeded| ResponseGenerator

Planner --> ActionQueue
ActionQueue --> ParameterResolver
ParameterResolver --> PolicyEngine
PolicyEngine --> PreExecutionChecker

%% 3. 控制层静态拦截 -> 写入快照并退出
PreExecutionChecker -->|需要澄清/触发风控| SnapshotStore
%% 写入快照时：graph_version++, 复制当前上下文到 xxx_snapshot，设置 mode=SUSPENDED
SnapshotStore -->|携带快照数据流转| ResponseGenerator

PreExecutionChecker -->|Ready| BudgetGuard
BudgetGuard --> ConsistencyChecker
ConsistencyChecker --> CapabilityRouter

%% 4. 执行层与确定性锁
CapabilityRouter --> InventoryCapability & ExpirationCapability & RecommendationCapability & BatchCapability & HouseholdCapability
InventoryCapability & ExpirationCapability & RecommendationCapability & BatchCapability & HouseholdCapability --> ToolExecutor

ToolExecutor --> ResultValidator
ResultValidator -->|Pass| StateUpdater
ResultValidator -->|Fail/Error| TaskEvaluator

%% 5. 版本递增与精准事件分发
StateUpdater -->|graph_version ++| Checkpoint
StateUpdater --> EventBus

EventBus --> EventRouter
EventRouter -->|精准订阅语义分发| WorkspaceStore & MemoryStore & InventoryCapability

Checkpoint --> TaskEvaluator

%% 6. 任务迭代与退出
TaskEvaluator -->|CONTINUE (Re-Plan)| LoopGuard
TaskEvaluator -->|动态拦截| SnapshotStore
TaskEvaluator -->|DONE| ResponseGenerator

ResponseGenerator --> Output
Output -.-> User

```

---

## 三、 5大核心工程隐患修复深度解析

### 1. Execution Context Versioning（执行版本快照）

* **原理解析**：当进入 `SUSPENDED` 模式时，系统不仅记录原因，还将当前的 `action_queue` 和 `workspace` 的深拷贝（Deep Copy）打包成一个 `Frame` 写入 `SnapshotStoreState`，并打上当前的 `graph_version`。
* **规避风险**：用户前端在确认一个高危操作时，可能由于网络延迟多点了两次，或者前端刷新重复发送确认请求。当第二个请求重入时，系统比对当前的 `graph_version` 与快照中的 `graph_version`。如果发现不一致（说明之前的快照已经被某个消费线程解冻并推进了），系统直接拒绝执行，彻底锁死**状态漂移**。

### 2. Re-entry Router（重入路由器）

* **逻辑控制**：这是图的唯一分流网关（Gateway）。
```python
def re_entry_routing(state: AgentGraphState) -> str:
    active_snapshot = snapshot_db.get(state.session_id)
    if active_snapshot and active_snapshot.is_suspended:
        # 提取历史栈帧，将全局模式变更为 RESUME
        state.execution_mode = "RESUME"
        return "route_to_snapshot_restore" 
    else:
        state.execution_mode = "NEW"
        return "route_to_new_planning"

```


* **规避风险**：消除了大模型意图识别的模糊性。不需要让大模型去猜“用户发这句‘确认’是不是针对刚才的操作”，由基础设施层强行执行确定性的**状态唤醒**。

### 3. Action Determinism Lock（动作幂等锁）

* **落地实践**：由 `Planner` 在规划出 action 的瞬间，使用哈希算法生成：

$$\text{idempotency\_key} = \text{hash}(\text{session\_id} + \text{graph\_version} + \text{tool\_name} + \text{arguments})$$


* **规避风险**：在 `ToolExecutor` 真正拉起外部 API 或物理数据库前，先走分布式锁（如 Redis / DB 唯一索引）做一次 `SETNX` 或 `INSERT` 校验。即使 `TaskEvaluator` 重跑或者用户疯狂刷新，只要对应的 `idempotency_key` 已经被标记为 `SUCCESS`，后续的执行请求会被直接拦截并返回缓存结果，确保核心业务（如“扣减库存”、“发送临期短信”）**绝不发生重执行**。

### 4. EventRouter 精准路由

* **重构方案**：废除无脑的全局广播。`EventRouter` 作为一个纯粹的 **Topic-based Filter**。
* **落地细节**：比如当 `InventoryCapability` 完成了物资扣减，触发 `InventoryChanged` 事件。`EventRouter` 会解析事件的 `scope`（当前会话）和 `type`，仅仅通知 `WorkspaceStore` 去局部擦写内存，而不会错透给 `MemoryStore`（写污染）或者意外重新激活其他 Capability。

### 5. 全局执行状态机（Execution Mode）

* **NEW**：全新任务，走完整的意图解析与 Planner 全局规划。
* **RESUME**：重入任务。此时图会快进（Fast-Forward）跳过意图分类和大模型全局规划，直接解冻 `action_queue_snapshot`，把用户的输入塞进阻塞的那一步 Action 的参数里，继续向下执行。
* **SUSPENDED**：挂起任务。表明执行链被成功截断。
* **REPLAY**：系统容灾或审计模式。图会基于 `Checkpoint` 和幂等锁重新跑一遍状态变化，用于追溯系统故障。

经过这一轮全面打补丁，你的架构已经完成了从“应用层逻辑图”到“分布式高并发智能体内核”的全面蜕变。