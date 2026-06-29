"""新架构领域模型与 Graph State 定义。

本模块定义 LangGraph 重构后的核心数据结构：
- UserContext: 多家庭成员身份上下文
- ItemInstance: 物品仓储实例 (Instance) —— 每个单品有独立 ID
- PendingOperation: 被挂起的待确认事务声明
- merge_audit_logs: 自定义 Reducer，用于增量合并审计日志
- ExtendedGraphState: 全新全局流转状态 (Graph State)
"""

from typing import Annotated, Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field
from datetime import datetime


# ==========================================
# 1. 基础领域模型 (Domain Models)
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
# 2. 自定义 Reducer：用于 Annotated 增量日志
# ==========================================


def merge_audit_logs(old_logs: List[Dict[str, Any]], new_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """自定义Reducers：用于增量合并审计日志"""
    return old_logs + new_logs


# ==========================================
# 3. LangGraph 全局状态定义 (Graph State)
# ==========================================


class ExtendedGraphState(TypedDict, total=False):
    """下一代多模态家庭资产 Agent 的全局流转状态 (Graph State)

    total=False 允许额外的内部辅助字段（如 _inventory、_last_added_item）在图中传递。
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
