from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

ItemTag = Literal["告急", "较低", "充足", "过期预警"]
InventoryCategory = Literal["food", "medicine", "electronics", "cosmetics", "book", "other"]
NodeType = Literal["Zone", "Fixture", "Container", "Slot"]
ChatIntent = Literal[
    "add",
    "consume",
    "remove",
    "update_location",
    "update_expiry",
    "update_remark",
    "update_remaining",
    "expiry_query",
    "location_query",
    "quantity_query",
    "query_total",
    "search_query",
    "idle_query",
    "recipe",
    "chat",
]
ChatOperationType = Literal["add", "consume", "remove", "update"]


class Space(BaseModel):
    id: str
    name: str
    icon: str = "kitchen"
    count: int = 0
    warnCount: int = 0
    bgClass: str = "bg-primary-fixed"
    textColor: str = "text-primary"
    badgeColor: str = "bg-secondary-container"


class SKU(BaseModel):
    """产品定义——描述一种物品的固定属性。"""
    sku_id: str = ""
    title: str = "无名物品"
    category: InventoryCategory = "other"
    unit: str = "个"
    remind_days_before: int = Field(default=5, ge=0)
    tags: list[str] = Field(default_factory=list)
    icon: str = "package_2"
    created_at: str = ""
    updated_at: str = ""


class ItemInstance(BaseModel):
    """实物实例——描述一个具体批次/单件的动态状态。"""
    instance_id: str = ""
    sku_id: str = ""
    space_id: str = "kitchen"
    location: str = "默认层架"
    quantity: int = Field(default=1, ge=0)
    remaining_pct: int = Field(default=100, ge=0, le=100)
    buy_date: str | None = None
    expire_date: str | None = None
    is_opened: bool = False
    opened_date: str | None = None
    pao_days: int = Field(default=0, ge=0)
    final_expiry_date: str | None = None
    belongs_to_slot_id: str | None = None
    last_modified_by: str = "system"
    created_at: str = ""
    updated_at: str = ""


class SpatialNode(BaseModel):
    """空间节点——描述存放位置（区域/固定装置/容器/槽位）。"""
    node_id: str = ""
    node_type: NodeType = "Slot"
    parent_id: str | None = None
    name: str = ""
    aliases: list[str] = Field(default_factory=list)
    created_at: str = ""


class ConflictWarning(BaseModel):
    """多租户冲突预警。"""
    other_user: str = ""
    sku_title: str = ""
    action_type: str = ""
    time_ago_hours: float = 0.0
    warning_text: str = ""


class Item(BaseModel):
    id: str | None = None
    title: str = "无名物品"
    category: InventoryCategory = "other"
    spaceId: str = "kitchen"
    spaceName: str = "主厨房"
    location: str = "默认层架"
    remainingPct: int = Field(default=100, ge=0, le=100)
    buyDate: str | None = None
    expireDate: str | None = None
    tag: ItemTag | None = None
    count: int = Field(default=1, ge=0)
    unit: str = "个"
    remindDaysBefore: int = Field(default=5, ge=0)
    tags: list[str] = Field(default_factory=list)
    remark: str | None = None
    icon: str = "package_2"
    # === 新字段（来自 SKU+Instance 模型，可选向后兼容） ===
    isOpened: bool = False
    openedDate: str | None = None
    paoDays: int = Field(default=0, ge=0)
    finalExpiryDate: str | None = None
    belongsToSlotId: str | None = None
    skuId: str | None = None
    instanceId: str | None = None


class Message(BaseModel):
    id: str
    sender: Literal["user", "assistant"]
    text: str
    timestamp: str = "刚刚"
    type: Literal["text", "voice", "action_card", "welcome"] = "text"
    voiceDuration: str | None = None
    actionCard: dict[str, Any] | None = None
    itemSuggestion: dict[str, Any] | None = None


class ChatOperation(BaseModel):
    type: ChatOperationType
    target: str | None = None
    item: Item | None = None
    patch: dict[str, Any] | None = None
    consumeAll: bool = False
    removeReason: str | None = None


class ChatResult(BaseModel):
    intent: ChatIntent = "chat"
    replyText: str = "我已经处理完这次请求。"
    operations: list[ChatOperation] = Field(default_factory=list)
    itemSuggestion: dict[str, Any] | None = None
    needsConfirmation: bool = False
    pendingId: str | None = None
    # === 物品选择交互状态（跨轮次持久化） ===
    confirmedItemId: str | None = None  # 用户确认选择的物品 ID
    confirmedAllItems: bool = False     # 用户选择"全部"
    confirmedDeductCount: int | None = None  # 用户消耗数量（None=全部消耗）
    confirmedPatch: dict[str, Any] | None = None  # 确认后要执行的属性修改（如 {"location": "冰箱上层"}）
    # === 多选支持（新增） ===
    confirmedItemIds: list[str] = Field(default_factory=list)  # 用户确认选择的多个物品 ID（多选）
    confirmedDeductCounts: dict[str, int] = Field(default_factory=dict)  # 每个物品的扣减数量 {item_id: count}
    # === 冲突检测 ===
    conflictCheckSkus: list[str] = Field(default_factory=list)  # 需要做冲突检测的 SKU 名称列表


class ConfirmRequest(BaseModel):
    pendingId: str
    items: list[Item]


class ConsumeConfirmRequest(BaseModel):
    pendingId: str
    selectedIndex: int = 0
    consumeAll: bool = False
    count: int | None = None


class FrontendInventoryItem(BaseModel):
    id: str
    name: str
    category: InventoryCategory
    quantity: int = Field(ge=0)
    unit: str
    location: str
    purchaseDate: str
    expiryDate: str | None = None
    remindDaysBefore: int = Field(ge=0)
    tags: list[str] = Field(default_factory=list)
    note: str = ""


class SystemPreferences(BaseModel):
    allergies: list[str] = Field(default_factory=list)
    lifestyle: str = "均衡饮食"
    warningThreshold: int = 5
    lowThreshold: int = 15
    reminderTime: str = "18:00"
    savingPath: str = "./storage/inventory.md"
    aiModel: str = "gpt-4o-mini"
    temperature: float = 0.7
    autoTag: bool = True
    selectedLocations: list[str] = Field(default_factory=list)
    expirationStrategy: Literal["normal", "strict", "relaxed"] = "normal"
    squirrelPersonality: Literal["humorous", "gabby", "gentle", "strict_squirrel"] = "humorous"


class AppState(BaseModel):
    onboardingDone: bool = True
    spaces: list[Space]
    items: list[Item]
    messages: list[Message]
    preferences: SystemPreferences


class TextRequest(BaseModel):
    text: str


class ChatConfirmation(BaseModel):
    decision: Literal["confirm", "cancel"]
    items: list[Item] = Field(default_factory=list)


class ChatRequest(BaseModel):
    chatHistory: list[Message] = Field(
        default_factory=list,
        validation_alias=AliasChoices("chatHistory", "messages"),
    )
    currentInventory: list[Item] = Field(default_factory=list)
    personality: str | None = None
    habits: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    # === 多租户身份 ===
    userId: str = "default_user"
    userName: str = "主人"
    confirmation: ChatConfirmation | None = None


class RecipeRequest(BaseModel):
    inventory: list[Item] = Field(default_factory=list)
    excludedRecipeTitle: str | None = None
    systemPreferences: SystemPreferences | None = None


class RecipeCard(BaseModel):
    recipe_name: str
    core_expiring_food: list[str]
    other_ingredients: list[str]
    cooking_steps: list[str]
    estimated_time: str
    difficulty: str
    waste_tip: str


class RecipeRecommendResult(BaseModel):
    title: str
    subtitle: str
    intro: str
    recipe_list: list[RecipeCard]
    summary_tip: str
