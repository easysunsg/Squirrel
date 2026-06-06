from typing import Any, Literal

from pydantic import BaseModel, Field

ItemTag = Literal["告急", "较低", "充足", "过期预警"]


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
    spaceId: str = "kitchen"
    spaceName: str = "主厨房"
    location: str = "默认层架"
    remainingPct: int = Field(default=100, ge=0, le=100)
    buyDate: str | None = None
    expireDate: str | None = None
    tag: ItemTag | None = None
    count: int = Field(default=1, ge=0)
    unit: str = "个"
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


class SystemPreferences(BaseModel):
    allergies: list[str] = []
    lifestyle: str = "均衡饮食"
    warningThreshold: int = 5
    lowThreshold: int = 15
    reminderTime: str = "18:00"
    savingPath: str = "./storage/inventory.md"
    aiModel: str = "gpt-4o-mini"
    temperature: float = 0.7
    autoTag: bool = True


class AppState(BaseModel):
    onboardingDone: bool = True
    spaces: list[Space]
    items: list[Item]
    messages: list[Message]
    preferences: SystemPreferences


class TextRequest(BaseModel):
    text: str


class ChatRequest(BaseModel):
    chatHistory: list[Message] = []
    currentInventory: list[Item] = []


class RecipeRequest(BaseModel):
    inventory: list[Item] = []
    excludedRecipeTitle: str | None = None
    systemPreferences: SystemPreferences | None = None
