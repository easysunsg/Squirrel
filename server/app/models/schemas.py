from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

ItemTag = Literal["告急", "较低", "充足", "过期预警"]
InventoryCategory = Literal["food", "medicine", "electronics", "cosmetics", "book", "other"]
ChatIntent = Literal[
    "add",
    "consume",
    "remove",
    "update_location",
    "update_expiry",
    "update_remaining",
    "expiry_query",
    "location_query",
    "quantity_query",
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


class ChatRequest(BaseModel):
    chatHistory: list[Message] = Field(
        default_factory=list,
        validation_alias=AliasChoices("chatHistory", "messages"),
    )
    currentInventory: list[Item] = Field(default_factory=list)
    personality: str | None = None
    habits: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)


class RecipeRequest(BaseModel):
    inventory: list[Item] = Field(default_factory=list)
    excludedRecipeTitle: str | None = None
    systemPreferences: SystemPreferences | None = None
