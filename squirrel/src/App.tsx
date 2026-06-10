import React, { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  Archive,
  LayoutDashboard,
  Menu,
  MessageSquare,
  Settings as SettingsIcon,
  X,
} from "lucide-react";
import { ChatTab } from "./components/ChatTab";
import { DashboardTab } from "./components/DashboardTab";
import { Drawer } from "./components/Drawer";
import { InventoryTab } from "./components/InventoryTab";
import { Onboarding } from "./components/Onboarding";
import { SettingsTab } from "./components/SettingsTab";
import { AppSettings, ChatApiResponse, ChatMessage, DrawerActionType, InventoryCategory, InventoryItem } from "./types";
import { DEFAULT_INVENTORY_ITEMS } from "./utils";

const DEFAULT_SETTINGS: AppSettings = {
  onboardingComplete: false,
  selectedLocations: ["主冰箱", "厨房储物柜", "玄关柜"],
  dietaryHabits: [],
  lifestyleTag: "减脂增肌中",
  reminderTime: "18:00",
  expirationStrategy: "normal",
  squirrelPersonality: "humorous",
};

const DEFAULT_CHAT_MESSAGE: ChatMessage = {
  id: "msg-init-local",
  sender: "assistant",
  text: "欢迎来到松鼠树洞，我们可以开始记录库存、整理物品，或者直接聊天。",
  timestamp: "刚刚",
};

type ServerInventoryItem = {
  id?: string | null;
  title?: string;
  category?: InventoryCategory;
  spaceId?: string;
  spaceName?: string;
  location?: string;
  remainingPct?: number;
  buyDate?: string | null;
  expireDate?: string | null;
  tag?: string | null;
  count?: number;
  unit?: string;
  remindDaysBefore?: number;
  tags?: string[];
  remark?: string | null;
  icon?: string;
};

type ServerStatePayload = {
  onboardingDone?: boolean;
  spaces?: Array<{ name?: string }>;
  items?: ServerInventoryItem[];
  preferences?: {
    allergies?: string[];
    lifestyle?: string;
    reminderTime?: string;
    selectedLocations?: string[];
    expirationStrategy?: AppSettings["expirationStrategy"];
    squirrelPersonality?: AppSettings["squirrelPersonality"];
  };
};

function normalizeSettingsFromServer(payload: ServerStatePayload): AppSettings {
  const selectedLocations = payload.preferences?.selectedLocations?.filter(Boolean)
    || payload.spaces?.map((space) => space.name).filter((name): name is string => Boolean(name && name.trim()))
    || DEFAULT_SETTINGS.selectedLocations;

  return {
    onboardingComplete: payload.onboardingDone ?? DEFAULT_SETTINGS.onboardingComplete,
    selectedLocations,
    dietaryHabits: payload.preferences?.allergies ?? DEFAULT_SETTINGS.dietaryHabits,
    lifestyleTag: payload.preferences?.lifestyle ?? DEFAULT_SETTINGS.lifestyleTag,
    reminderTime: payload.preferences?.reminderTime ?? DEFAULT_SETTINGS.reminderTime,
    expirationStrategy: payload.preferences?.expirationStrategy ?? DEFAULT_SETTINGS.expirationStrategy,
    squirrelPersonality: payload.preferences?.squirrelPersonality ?? DEFAULT_SETTINGS.squirrelPersonality,
  };
}

function buildServerStateFromSettings(nextSettings: AppSettings) {
  const locationSpaceStyles = [
    { icon: "kitchen", bgClass: "bg-primary-fixed", textColor: "text-primary", badgeColor: "bg-secondary-container" },
    { icon: "shelves", bgClass: "bg-tertiary-fixed", textColor: "text-tertiary", badgeColor: "bg-surface-container-high" },
    { icon: "garage", bgClass: "bg-secondary-fixed", textColor: "text-secondary", badgeColor: "bg-surface-container-high" },
    { icon: "home_storage", bgClass: "bg-surface-container-high", textColor: "text-outline", badgeColor: "bg-surface-container" },
  ] as const;

  const warningThresholdMap = {
    strict: 10,
    normal: 5,
    relaxed: 2,
  } as const;

  return {
    onboardingDone: nextSettings.onboardingComplete,
    spaces: nextSettings.selectedLocations.map((name, index) => ({
      id: `space-${index + 1}`,
      name,
      ...locationSpaceStyles[index % locationSpaceStyles.length],
    })),
    preferences: {
      allergies: nextSettings.dietaryHabits,
      lifestyle: nextSettings.lifestyleTag,
      warningThreshold: warningThresholdMap[nextSettings.expirationStrategy],
      lowThreshold: 15,
      reminderTime: nextSettings.reminderTime,
      savingPath: "./storage/inventory.md",
      aiModel: "gpt-4o-mini",
      temperature: 0.7,
      autoTag: true,
      selectedLocations: nextSettings.selectedLocations,
      expirationStrategy: nextSettings.expirationStrategy,
      squirrelPersonality: nextSettings.squirrelPersonality,
    },
  };
}

function normalizeServerItem(item: ServerInventoryItem, index: number): InventoryItem {
  return {
    id: item.id || `item-server-${index}`,
    name: item.title || "无名物品",
    category: item.category || "other",
    quantity: item.count ?? 1,
    unit: item.unit || "个",
    location: item.location || item.spaceName || "默认层架",
    purchaseDate: item.buyDate || new Date().toISOString().split("T")[0],
    expiryDate: item.expireDate || undefined,
    remindDaysBefore: item.remindDaysBefore ?? 5,
    tags: item.tags || [],
    note: item.remark || "",
  };
}

function normalizeServerItems(value: unknown): InventoryItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.map((item, index) => normalizeServerItem(item as ServerInventoryItem, index));
}

function buildServerItemFromInventory(item: InventoryItem, settings: AppSettings): ServerInventoryItem {
  const spaceIndex = settings.selectedLocations.indexOf(item.location);
  const spaceId = spaceIndex >= 0 ? `space-${spaceIndex + 1}` : "space-custom";

  return {
    id: item.id,
    title: item.name,
    category: item.category,
    spaceId,
    spaceName: item.location,
    location: item.location,
    remainingPct: 100,
    buyDate: item.purchaseDate,
    expireDate: item.expiryDate || null,
    count: item.quantity,
    unit: item.unit,
    remindDaysBefore: item.remindDaysBefore,
    tags: item.tags,
    remark: item.note,
  };
}

function normalizeMessage(message: Partial<ChatMessage>, index: number): ChatMessage {
  return {
    id: message.id || `msg-${index}-${Date.now()}`,
    sender: message.sender === "user" ? "user" : "assistant",
    text: message.text || "",
    timestamp: message.timestamp || "刚刚",
    itemSuggestion: message.itemSuggestion,
  };
}

function normalizeMessageList(value: unknown): ChatMessage[] {
  if (!Array.isArray(value)) {
    return [DEFAULT_CHAT_MESSAGE];
  }

  const messages = value.map((message, index) => normalizeMessage(message, index));
  return messages.length > 0 ? messages : [DEFAULT_CHAT_MESSAGE];
}

function createChatMessage(sender: ChatMessage["sender"], text: string, itemSuggestion?: ChatMessage["itemSuggestion"]): ChatMessage {
  return {
    id: `msg-${sender}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    sender,
    text,
    timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    itemSuggestion,
  };
}

function createFallbackReply(text: string, settings: AppSettings, items: InventoryItem[]): ChatMessage {
  const itemNames = items.slice(0, 4).map((item) => item.name).join("、") || "当前库存";
  return createChatMessage(
    "assistant",
    `收到「${text}」。后端暂时不可用，我先用本地模式回应：我会结合你的生活标签「${settings.lifestyleTag}」和 ${settings.reminderTime} 的提醒时间来处理。当前可参考的库存有：${itemNames}。`
  );
}

export default function App() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([DEFAULT_CHAT_MESSAGE]);
  const [isSendingMessage, setIsSendingMessage] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [chatPreinput, setChatPreinput] = useState("");
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [drawerAction, setDrawerAction] = useState<DrawerActionType>("view");
  const [selectedDrawerItem, setSelectedDrawerItem] = useState<InventoryItem | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const loadInitialState = async () => {
      try {
        const response = await fetch("/api/state");
        if (!response.ok) {
          throw new Error(`Failed to load state: ${response.status}`);
        }

        const data = (await response.json()) as ServerStatePayload;
        const serverSettings = normalizeSettingsFromServer(data);
        const serverItems = normalizeServerItems(data.items);
        setSettings(serverSettings);
        setItems(serverItems);
        localStorage.setItem("squirrel_nest_settings", JSON.stringify(serverSettings));
        localStorage.setItem("squirrel_nest_inventory", JSON.stringify(serverItems));
      } catch (error) {
        console.error("Failed to load state from server", error);
        const savedConfig = localStorage.getItem("squirrel_nest_settings");
        if (savedConfig) {
          try {
            setSettings({ ...DEFAULT_SETTINGS, ...JSON.parse(savedConfig) });
          } catch (parseError) {
            console.error("Failed to read settings from localStorage", parseError);
          }
        }

        const savedItems = localStorage.getItem("squirrel_nest_inventory");
        if (savedItems) {
          try {
            setItems(JSON.parse(savedItems));
          } catch (parseError) {
            console.error("Failed to read inventory from localStorage", parseError);
            setItems(DEFAULT_INVENTORY_ITEMS);
          }
        } else {
          setItems(DEFAULT_INVENTORY_ITEMS);
          localStorage.setItem("squirrel_nest_inventory", JSON.stringify(DEFAULT_INVENTORY_ITEMS));
        }
      }
    };

    void loadInitialState();

    const loadMessages = async () => {
      try {
        const response = await fetch("/api/messages");
        if (!response.ok) {
          throw new Error(`Failed to load messages: ${response.status}`);
        }
        const data = await response.json();
        setMessages(normalizeMessageList(data.messages));
      } catch (error) {
        console.error("Failed to load messages from server", error);
        const savedChat = localStorage.getItem("squirrel_nest_chat_hist");
        if (savedChat) {
          try {
            setMessages(normalizeMessageList(JSON.parse(savedChat)));
            return;
          } catch (parseError) {
            console.error("Failed to read local chat history", parseError);
          }
        }
        setMessages([DEFAULT_CHAT_MESSAGE]);
      }
    };

    void loadMessages();
  }, []);

  useEffect(() => {
    localStorage.setItem("squirrel_nest_chat_hist", JSON.stringify(messages));
  }, [messages]);

  const saveSettingsToStorage = (nextSettings: AppSettings) => {
    setSettings(nextSettings);
    localStorage.setItem("squirrel_nest_settings", JSON.stringify(nextSettings));
  };

  const persistSettings = async (nextSettings: AppSettings) => {
    const response = await fetch("/api/state", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(buildServerStateFromSettings(nextSettings)),
    });

    if (!response.ok) {
      throw new Error(`Failed to save settings: ${response.status}`);
    }

    saveSettingsToStorage(nextSettings);
  };

  const saveItemsToStorage = (nextItems: InventoryItem[]) => {
    setItems(nextItems);
    localStorage.setItem("squirrel_nest_inventory", JSON.stringify(nextItems));
  };

  const handleOnboardingComplete = async (nextSettings: AppSettings) => {
    await persistSettings(nextSettings);
    setActiveTab("dashboard");
  };

  const handleSaveItem = async (itemToSave: InventoryItem) => {
    const exists = items.some((item) => item.id === itemToSave.id);
    const response = await fetch(exists ? `/api/items/${itemToSave.id}` : "/api/items", {
      method: exists ? "PATCH" : "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(buildServerItemFromInventory(itemToSave, settings)),
    });

    if (!response.ok) {
      throw new Error(`Failed to save item: ${response.status}`);
    }

    const savedItem = normalizeServerItem((await response.json()) as ServerInventoryItem, 0);
    const nextItems = exists
      ? items.map((item) => (item.id === savedItem.id ? savedItem : item))
      : [savedItem, ...items];
    saveItemsToStorage(nextItems);
  };

  const handleDeleteItem = async (id: string) => {
    const response = await fetch(`/api/items/${id}`, { method: "DELETE" });
    if (!response.ok) {
      throw new Error(`Failed to delete item: ${response.status}`);
    }
    saveItemsToStorage(items.filter((item) => item.id !== id));
  };

  const handleQuickCleanItem = async (id: string) => {
    await handleDeleteItem(id);
  };

  const appendChatMessage = (message: ChatMessage) => {
    setMessages((currentMessages) => [...currentMessages, message]);
  };

  const handleSendChatMessage = async (text: string) => {
    const userMessage = createChatMessage("user", text);
    const nextMessages = [...messages, userMessage];

    setMessages(nextMessages);
    setChatError(null);
    setIsSendingMessage(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          chatHistory: nextMessages,
          personality: settings.squirrelPersonality,
          habits: settings.dietaryHabits,
          locations: settings.selectedLocations,
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to send chat message: ${response.status}`);
      }

      const data = (await response.json()) as ChatApiResponse;
      if (Array.isArray(data.items)) {
        const serverItems = normalizeServerItems(data.items);
        saveItemsToStorage(serverItems);
      }

      if (Array.isArray(data.messages)) {
        setMessages(normalizeMessageList(data.messages));
        return;
      }

      if (data.reply) {
        appendChatMessage(createChatMessage("assistant", data.reply, data.itemSuggestion));
        return;
      }

      throw new Error("Chat response did not include messages or reply");
    } catch (error) {
      console.error("Failed to send chat message", error);
      setChatError("后端暂时不可用，已使用本地回复。");
      setMessages([...nextMessages, createFallbackReply(text, settings, items)]);
    } finally {
      setIsSendingMessage(false);
    }
  };

  const handleClearChatHistory = async () => {
    setChatError(null);
    try {
      const response = await fetch("/api/messages", { method: "DELETE" });
      if (!response.ok) {
        throw new Error(`Failed to clear messages: ${response.status}`);
      }
      const data = await response.json();
      setMessages(normalizeMessageList(data.messages));
    } catch (error) {
      console.error("Failed to clear messages on server", error);
      setChatError("后端清空失败，已在本地重置聊天记录。");
      setMessages([DEFAULT_CHAT_MESSAGE]);
    }
  };

  const handleResetFactoryData = () => {
    localStorage.removeItem("squirrel_nest_settings");
    localStorage.removeItem("squirrel_nest_inventory");
    localStorage.removeItem("squirrel_nest_chat_hist");
    setSettings(DEFAULT_SETTINGS);
    setItems(DEFAULT_INVENTORY_ITEMS);
    setMessages([DEFAULT_CHAT_MESSAGE]);
    setActiveTab("dashboard");
  };

  const handleViewItem = (item: InventoryItem) => {
    setSelectedDrawerItem(item);
    setDrawerAction("view");
    setIsDrawerOpen(true);
  };

  const handleCreateNewItem = () => {
    setSelectedDrawerItem(null);
    setDrawerAction("create");
    setIsDrawerOpen(true);
  };

  if (!settings.onboardingComplete) {
    return <Onboarding settings={settings} onSaveSettings={handleOnboardingComplete} />;
  }

  const navItems = [
    { id: "dashboard", label: "仓储大盘", icon: LayoutDashboard },
    { id: "inventory", label: "小窝存根", icon: Archive },
    { id: "chat", label: "树洞聊斋", icon: MessageSquare },
    { id: "settings", label: "控制台", icon: SettingsIcon },
  ];

  return (
    <div className="min-h-screen bg-background bg-paper text-on-background font-sans flex flex-col md:flex-row">
      <Drawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        action={drawerAction}
        item={selectedDrawerItem}
        locations={settings.selectedLocations}
        onSave={handleSaveItem}
        onDelete={handleDeleteItem}
      />

      <aside className="hidden md:flex w-64 shrink-0 flex-col justify-between border-r-4 border-on-background bg-white p-5">
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <span className="text-4xl">🐿️</span>
            <div>
              <h1 className="font-display text-lg font-medium leading-none">松鼠筑巢</h1>
              <p className="mt-1 text-[10px] uppercase tracking-wide text-outline">Smart Home Nest</p>
            </div>
          </div>

          <nav className="space-y-2">
            {navItems.map((tab) => {
              const TabIcon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex w-full items-center gap-3 rounded-xl border-2 px-4 py-3 text-sm font-display font-bold transition-colors ${
                    isActive
                      ? "border-on-background bg-primary text-white shadow-[2px_3px_0_0_#1b1c1c]"
                      : "border-transparent text-outline hover:bg-slate-100"
                  }`}
                >
                  <TabIcon size={18} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="border-t pt-4 text-[10px] leading-relaxed text-outline">
          <p>提醒时间: {settings.reminderTime}</p>
          <p>生活标签: {settings.lifestyleTag}</p>
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex items-center justify-between border-b-2 border-on-background bg-white p-4 md:hidden">
        <div className="flex items-center gap-2">
          <span className="text-3xl">🐿️</span>
          <div>
            <h1 className="text-[15px] font-display font-medium leading-none">松鼠筑巢</h1>
            <p className="text-[9px] text-outline">聊天与库存助手</p>
          </div>
        </div>
        <button
          onClick={() => setMobileMenuOpen((open) => !open)}
          className="rounded-lg border-2 border-on-background bg-surface-container p-1.5"
        >
          {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      </header>

      <AnimatePresence>
        {mobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="absolute left-0 top-[64px] z-20 w-full space-y-2 border-b-4 border-on-background bg-white p-4 shadow-xl md:hidden"
          >
            {navItems.map((tab) => {
              const TabIcon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => {
                    setActiveTab(tab.id);
                    setMobileMenuOpen(false);
                  }}
                  className={`flex w-full items-center gap-3 rounded-xl border-2 px-4 py-3 text-sm font-display font-bold ${
                    isActive
                      ? "border-on-background bg-primary text-white shadow-[2px_3px_0_0_#1b1c1c]"
                      : "border-transparent text-outline hover:bg-slate-100"
                  }`}
                >
                  <TabIcon size={16} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>

      <main className="mx-auto w-full max-w-7xl flex-1 overflow-x-hidden p-4 md:p-6 lg:p-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.15 }}
          >
            {activeTab === "dashboard" && (
              <DashboardTab
                items={items}
                settings={settings}
                onNavigateToTab={setActiveTab}
                onSetChatPreinput={setChatPreinput}
                onQuickCleanItem={handleQuickCleanItem}
                onViewItem={handleViewItem}
              />
            )}

            {activeTab === "inventory" && (
              <InventoryTab
                items={items}
                settings={settings}
                onViewItem={handleViewItem}
                onEditItem={(item) => {
                  setSelectedDrawerItem(item);
                  setDrawerAction("edit");
                  setIsDrawerOpen(true);
                }}
                onDeleteItem={handleDeleteItem}
                onCreateNewItem={handleCreateNewItem}
              />
            )}

            {activeTab === "chat" && (
              <ChatTab
                settings={settings}
                items={items}
                preinput={chatPreinput}
                onClearPreinput={() => setChatPreinput("")}
                onSaveNewItem={handleSaveItem}
                onSendMessage={handleSendChatMessage}
                onAppendLocalMessage={appendChatMessage}
                onClearChatHistory={() => {
                  void handleClearChatHistory();
                }}
                messages={messages}
                isSendingMessage={isSendingMessage}
                chatError={chatError}
              />
            )}

            {activeTab === "settings" && (
              <SettingsTab
                settings={settings}
                onUpdateSettings={persistSettings}
                onResetFactoryData={handleResetFactoryData}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
