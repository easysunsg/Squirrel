flowchart TD

User([User])

%% ==========================================
%% INPUT & COMPOSITE CONTEXT LAYER (Source)
%% ==========================================
subgraph INPUT_LAYER [输入与现场恢复层]
NormalizeRequest[NormalizeRequest]

    subgraph CONTEXT_CONTAINER [Context Architecture]
        SnapshotStore[(SnapshotStore <br/><i>*挂起快照/现场恢复</i>)]
        WorkspaceStore[(WorkspaceStore <br/><i>*当前会话/临时变量</i>)]
        MemoryStore[(MemoryStore <br/><i>*长期记忆/用户画像</i>)]
    end
    
    ReferenceResolver[ReferenceResolver]
    GoalManager[GoalManager]
    IntentClassifier[IntentClassifier]
end

%% ==========================================
%% BRAIN & GUARD LAYER
%% ==========================================
subgraph BRAIN_LLM [动态规划大脑]
LoopGuard{LoopGuard <br/><i>*深度熔断器 depth > N ?</i>}
Planner[Planner]
ActionQueue[ActionQueue]
end

%% ==========================================
%% CONTROL & CHECK LAYER
%% ==========================================
subgraph CONTROL_LAYER [控制与风控层]
ParameterResolver[ParameterResolver]
PolicyEngine[PolicyEngine]
PreExecutionChecker{PreExecutionChecker <br/><i>*静态拦截器</i>}

    BudgetGuard[BudgetGuard]
    ConsistencyChecker[ConsistencyChecker]
    CapabilityRouter[CapabilityRouter]
end

%% ==========================================
%% CAPABILITIES & EXECUTION
%% ==========================================
subgraph CAPABILITIES [能力域与工具执行]
InventoryCapability[InventoryCapability]
ExpirationCapability[ExpirationCapability]
RecommendationCapability[RecommendationCapability]
BatchCapability[BatchCapability]
HouseholdCapability[HouseholdCapability]

    ToolExecutor[ToolExecutor]
    ResultValidator{ResultValidator}
    StateUpdater[StateUpdater]
    EventBus[EventBus]
    Checkpoint[Checkpoint]
    TaskEvaluator{TaskEvaluator <br/><i>*动态评估器</i>}
end

%% ==========================================
%% OUTPUT LAYER (Sink)
%% ==========================================
subgraph OUTPUT_LAYER [纯粹渲染层 - 无控制流]
ResponseGenerator[ResponseGenerator <br/><i>*仅负责 UI/文本 渲染</i>]
Output([Response])
end

%% ==========================================
%% LOGICAL FLOW LINES
%% ==========================================

%% 1. 启动与上下文装载 (Graph Restart 逻辑)
User --> NormalizeRequest
NormalizeRequest --> SnapshotStore

%% SnapshotStore 唤醒时，将历史快照恢复至 Workspace，同时合并新输入
SnapshotStore --> WorkspaceStore
WorkspaceStore & MemoryStore --> ReferenceResolver

ReferenceResolver --> GoalManager
GoalManager --> IntentClassifier

%% 2. 大脑规划与熔断拦截
IntentClassifier --> LoopGuard
LoopGuard -->|Depth OK| Planner
LoopGuard -->|Depth Exceeded / Fallback| ResponseGenerator

Planner --> ActionQueue
ActionQueue --> ParameterResolver
ParameterResolver --> PolicyEngine
PolicyEngine --> PreExecutionChecker

%% 3. 控制层静态分流 (发现缺失/高危，直接保存快照并走向终点)
PreExecutionChecker -->|1. 参数缺失 / 2. 触发高危拦截| SnapshotStore
SnapshotStore -->|隐式流转: 携带挂起原因| ResponseGenerator

PreExecutionChecker -->|Ready| BudgetGuard
BudgetGuard --> ConsistencyChecker
ConsistencyChecker --> CapabilityRouter

%% 4. 能力执行与校验
CapabilityRouter --> InventoryCapability & ExpirationCapability & RecommendationCapability & BatchCapability & HouseholdCapability
InventoryCapability & ExpirationCapability & RecommendationCapability & BatchCapability & HouseholdCapability --> ToolExecutor

ToolExecutor --> ResultValidator
ResultValidator -->|Validation Pass| StateUpdater
ResultValidator -->|Validation Fail/Error| TaskEvaluator

%% 事件总线仅做异步通知与底层的缓存/状态同步，不参与图的控制流
StateUpdater --> EventBus
StateUpdater --> Checkpoint
EventBus -.-> WorkspaceStore & MemoryStore & InventoryCapability

Checkpoint --> TaskEvaluator

%% 5. 任务评估分流 (Loop & Exit 哲学)
TaskEvaluator -->|CONTINUE / Re-Plan| LoopGuard

%% 执行中动态发现问题，同样走向快照层封存现场，准备退出
TaskEvaluator -->|动态参数缺失 / 动态触发风控| SnapshotStore

TaskEvaluator -->|DONE / Success| ResponseGenerator

%% 6. 纯粹的输出渲染 (叶子节点，图的生命周期在此彻底结束)
ResponseGenerator --> Output
Output -.->|等待用户产生新交互| User