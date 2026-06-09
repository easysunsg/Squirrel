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
import { AppSettings, ChatMessage, DrawerActionType, InventoryItem } from "./types";
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

function normalizeMessage(message: Partial<ChatMessage>, index: number): ChatMessage {
  return {
    id: message.id || `msg-${index}-${Date.now()}`,
    sender: message.sender === "user" ? "user" : "assistant",
    text: message.text || "",
    timestamp: message.timestamp || "刚刚",
    itemSuggestion: message.itemSuggestion,
  };
}

export default function App() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([DEFAULT_CHAT_MESSAGE]);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [chatPreinput, setChatPreinput] = useState("");
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [drawerAction, setDrawerAction] = useState<DrawerActionType>("view");
  const [selectedDrawerItem, setSelectedDrawerItem] = useState<InventoryItem | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const savedConfig = localStorage.getItem("squirrel_nest_settings");
    if (savedConfig) {
      try {
        setSettings({ ...DEFAULT_SETTINGS, ...JSON.parse(savedConfig) });
      } catch (error) {
        console.error("Failed to read settings from localStorage", error);
      }
    }

    const savedItems = localStorage.getItem("squirrel_nest_inventory");
    if (savedItems) {
      try {
        setItems(JSON.parse(savedItems));
      } catch (error) {
        console.error("Failed to read inventory from localStorage", error);
        setItems(DEFAULT_INVENTORY_ITEMS);
      }
    } else {
      setItems(DEFAULT_INVENTORY_ITEMS);
      localStorage.setItem("squirrel_nest_inventory", JSON.stringify(DEFAULT_INVENTORY_ITEMS));
    }

    const loadMessages = async () => {
      try {
        const response = await fetch("/api/messages");
        if (!response.ok) {
          throw new Error(`Failed to load messages: ${response.status}`);
        }
        const data = await response.json();
        const nextMessages = Array.isArray(data.messages)
          ? data.messages.map(normalizeMessage)
          : [DEFAULT_CHAT_MESSAGE];
        setMessages(nextMessages.length > 0 ? nextMessages : [DEFAULT_CHAT_MESSAGE]);
      } catch (error) {
        console.error("Failed to load messages from server", error);
        const savedChat = localStorage.getItem("squirrel_nest_chat_hist");
        if (savedChat) {
          try {
            setMessages(JSON.parse(savedChat));
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

  const saveItemsToStorage = (nextItems: InventoryItem[]) => {
    setItems(nextItems);
    localStorage.setItem("squirrel_nest_inventory", JSON.stringify(nextItems));
  };

  const handleOnboardingComplete = (nextSettings: AppSettings) => {
    saveSettingsToStorage(nextSettings);
    setActiveTab("dashboard");
  };

  const handleSaveItem = (itemToSave: InventoryItem) => {
    const exists = items.some((item) => item.id === itemToSave.id);
    const nextItems = exists
      ? items.map((item) => (item.id === itemToSave.id ? itemToSave : item))
      : [itemToSave, ...items];
    saveItemsToStorage(nextItems);
  };

  const handleDeleteItem = (id: string) => {
    saveItemsToStorage(items.filter((item) => item.id !== id));
  };

  const handleQuickCleanItem = (id: string) => {
    saveItemsToStorage(items.filter((item) => item.id !== id));
  };

  const handleSetMessages = (nextMessages: ChatMessage[]) => {
    setMessages(nextMessages);
  };

  const handleClearChatHistory = async () => {
    try {
      const response = await fetch("/api/messages", { method: "DELETE" });
      if (!response.ok) {
        throw new Error(`Failed to clear messages: ${response.status}`);
      }
      const data = await response.json();
      const nextMessages = Array.isArray(data.messages)
        ? data.messages.map(normalizeMessage)
        : [DEFAULT_CHAT_MESSAGE];
      setMessages(nextMessages);
    } catch (error) {
      console.error("Failed to clear messages on server", error);
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
    { id: "inventory", label: "树洞聊斋", icon: Archive },
    { id: "chat", label: "小窝存根", icon: MessageSquare },
    { id: "settings", label: "控制阀阁", icon: SettingsIcon },
  ];

  return (
    <div className="min-h-screen bg-background bg-paper text-on-background font-sans flex flex-col md:flex-row">
      <Drawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        action={drawerAction}
        item={selectedDrawerItem}
        locations={settings.selectedLocations}
        onSave={(savedItem) => {
          handleSaveItem(savedItem);
          setIsDrawerOpen(false);
        }}
        onDelete={(id) => {
          handleDeleteItem(id);
          setIsDrawerOpen(false);
        }}
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
                onPostChatMessage={handleSetMessages}
                onClearChatHistory={() => {
                  void handleClearChatHistory();
                }}
                messages={messages}
              />
            )}

            {activeTab === "settings" && (
              <SettingsTab
                settings={settings}
                onUpdateSettings={saveSettingsToStorage}
                onResetFactoryData={handleResetFactoryData}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
