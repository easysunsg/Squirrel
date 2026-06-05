import React, { useState, useEffect } from 'react';
import { Space, Item, Message, SystemPreferences } from './types';
import { 
  getStoredSpaces, saveStoredSpaces,
  getStoredItems, saveStoredItems,
  getStoredMessages, saveStoredMessages,
  getStoredPreferences, saveStoredPreferences,
  getOnboardingDone, setOnboardingDone,
  INITIAL_ITEMS, INITIAL_SPACES, INITIAL_MESSAGES, DEFAULT_PREFERENCES
} from './data';

import OnboardingView from './components/OnboardingView';
import DashboardView from './components/DashboardView';
import AssistantView from './components/AssistantView';
import InventoryView from './components/InventoryView';
import SettingsView from './components/SettingsView';

import { 
  Home, MessageCircle, Archive, Settings, Bell, Sparkles, LogOut, Clock, BookOpen, Layers
} from 'lucide-react';

export default function App() {
  // 1. Initial State Loaders
  const [onboardingDone, setOnboardingDoneState] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<string>('智能面板');
  const [items, setItems] = useState<Item[]>([]);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [preferences, setPreferences] = useState<SystemPreferences>(DEFAULT_PREFERENCES);

  const [notification, setNotification] = useState<string | null>(null);

  // Load everything on startup
  useEffect(() => {
    setOnboardingDoneState(getOnboardingDone());
    setItems(getStoredItems());
    setSpaces(getStoredSpaces());
    setMessages(getStoredMessages());
    setPreferences(getStoredPreferences());
  }, []);

  // Show a temporary banner notification
  const triggerBannerNotification = (text: string) => {
    setNotification(text);
    setTimeout(() => {
      setNotification(null);
    }, 4500);
  };

  // --- Core State Callbacks ---

  // Onboarding completion handler
  const handleOnboardingComplete = (newPrefs: Partial<SystemPreferences>, selectedSpaces: string[]) => {
    // 1. Set onboard state
    setOnboardingDone(true);
    setOnboardingDoneState(true);

    // 2. Build initialized spaces
    const initialSpacesBuilt: Space[] = selectedSpaces.map((name, i) => {
      const ids = ['refri', '柜子', 'entrance', 'meds', 'vanity', 'other'];
      const icons = ['kitchen', 'shelves', 'garage', 'kitchen', 'kitchen', 'kitchen'];
      const bgClasses = ['bg-primary-fixed', 'bg-tertiary-fixed', 'bg-secondary-fixed', 'bg-primary-fixed', 'bg-tertiary-fixed', 'bg-secondary-fixed'];
      
      return {
        id: `space-${i}-${Date.now()}`,
        name: name,
        icon: icons[i % icons.length],
        count: i === 0 ? 3 : 0,
        warnCount: 0,
        bgClass: bgClasses[i % bgClasses.length],
        textColor: 'text-on-surface',
        badgeColor: 'bg-secondary-container'
      };
    });

    // Save defaults
    const completePrefs = { ...preferences, ...newPrefs };
    setPreferences(completePrefs);
    saveStoredPreferences(completePrefs);

    setSpaces(initialSpacesBuilt);
    saveStoredSpaces(initialSpacesBuilt);

    // Seed 1-2 starting foods in their main refrigerator if selected
    if (selectedSpaces.includes('主冰箱')) {
      const starterItems: Item[] = [
        {
          id: 'starter-1',
          title: '新鲜纯牛奶',
          spaceId: initialSpacesBuilt[0].id,
          spaceName: '主冰箱',
          location: '主冷藏层柜',
          remainingPct: 80,
          buyDate: new Date().toISOString().split('T')[0],
          expireDate: '2026-12-15',
          tag: '充足',
          count: 2,
          unit: '盒',
          icon: 'kitchen',
          remark: '由设置向导自动赠送，开启健康整理记录！'
        }
      ];
      setItems(starterItems);
      saveStoredItems(starterItems);
    } else {
      setItems([]);
      saveStoredItems([]);
    }

    // Set fresh starting assistant message
    const welcomeMessages: Message[] = [
      {
        id: 'msg-start',
        sender: 'assistant',
        text: `哈喽！恭喜开启松鼠筑巢，我们已成功测绘了您的 ${selectedSpaces.join('、')} 物理生活空间！🐿️有什么录入的新采购或清理，随时吩咐小松鼠哦～`,
        timestamp: '刚刚',
        type: 'welcome'
      }
    ];
    setMessages(welcomeMessages);
    saveStoredMessages(welcomeMessages);

    setActiveTab('智能面板');
    triggerBannerNotification("🎉 筑巢测绘同步完成！欢迎来到松鼠家园！");
  };

  // Add Item to collection
  const handleAddItem = (newItemParams: Partial<Item>) => {
    const freshItem: Item = {
      id: 'item-' + Date.now(),
      title: newItemParams.title || '无名小坚果',
      spaceId: newItemParams.spaceId || 'kitchen',
      spaceName: newItemParams.spaceName || '主厨房',
      location: newItemParams.location || '桌角',
      remainingPct: newItemParams.remainingPct ?? 100,
      buyDate: newItemParams.buyDate || new Date().toISOString().split('T')[0],
      expireDate: newItemParams.expireDate || '2026-12-31',
      tag: newItemParams.tag || '充足',
      count: newItemParams.count || 1,
      unit: newItemParams.unit || '个',
      icon: newItemParams.icon || 'package_2',
      remark: newItemParams.remark || '手动登记入账。'
    };

    const newItems = [freshItem, ...items];
    setItems(newItems);
    saveStoredItems(newItems);

    triggerBannerNotification(`📥 已将 1件【${freshItem.title}】归档到储藏洞【${freshItem.spaceName}】！`);
  };

  // Update specific item specs
  const handleUpdateItem = (id: string, updatedParams: Partial<Item>) => {
    const updated = items.map((item) => {
      if (item.id === id) {
        return { ...item, ...updatedParams };
      }
      return item;
    });
    setItems(updated);
    saveStoredItems(updated);
  };

  // Delete/discard item
  const handleDeleteItem = (id: string) => {
    const itemToDelete = items.find(i => i.id === id);
    const filtered = items.filter(item => item.id !== id);
    setItems(filtered);
    saveStoredItems(filtered);

    if (itemToDelete) {
      triggerBannerNotification(`🧹 清空并清除了物品【${itemToDelete.title}】的库存。`);
    }
  };

  // Consume (reduce ratio)
  const handleConsumeItem = (id: string, deltaPct: number) => {
    const updated = items.map((item) => {
      if (item.id === id) {
        const newPct = Math.max(0, item.remainingPct - deltaPct);
        let tag: '告急' | '较低' | '充足' = '充足';
        if (newPct < 20) tag = '告急';
        else if (newPct < 50) tag = '较低';
        return { ...item, remainingPct: newPct, tag };
      }
      return item;
    });
    setItems(updated);
    saveStoredItems(updated);
  };

  // Chat memory sending callback
  const handleSendChatMessage = (msg: Message) => {
    const updatedMsgs = [...messages, msg];
    setMessages(updatedMsgs);
    saveStoredMessages(updatedMsgs);
  };

  // AI response logging callback
  const handleReceiveAIResponse = (text: string, cardData: any) => {
    const aiId = 'ai-' + Date.now();
    const aiMsg: Message = {
      id: aiId,
      sender: 'assistant',
      text,
      timestamp: '刚刚',
      type: cardData ? 'action_card' : 'text',
      actionCard: cardData ? {
        title: cardData.title,
        image: cardData.image || "https://lh3.googleusercontent.com/aida-public/AB6AXuAi0e0pMmh7n9_aGTW81tBycuiOEyAZPQx9amTGNI61Tv6lVT4Cy-EJ7aNh_Jk4aJV3gAJ9c2L6_pM2Rzalf78pA3hiaojD3WUXPGNsCVyMz0RmYHmDvBTj5IYh-9d9FDeB59eiXWLIcQEsNdWQuQqYNdEwJaHhPkIjRymaNmxfiAi0EE30ZVL_HWQS5-YbunGoYMbW_0qHo_2e-l32j1TUiNFhLAEBJmGWkk3iaJlEG3fPm8vwTzK9AOaV_BXT2YvPC4IbCfyP1g5i",
        category: cardData.category,
        quantity: cardData.quantity,
        spaceName: cardData.spaceName
      } : undefined
    };

    const updated = [...messages, aiMsg];
    setMessages(updated);
    saveStoredMessages(updated);
    triggerBannerNotification("🐿️ 收到松鼠管家新传信呼应！");
  };

  // Save Preferences
  const handleSavePreferences = (updated: SystemPreferences) => {
    setPreferences(updated);
    saveStoredPreferences(updated);
    triggerBannerNotification("⚙️ 系统阈值/AI设定偏好保存生效！");
  };

  // Absolute Wipe database
  const handleResetAllData = () => {
    localStorage.removeItem('nest_spaces');
    localStorage.removeItem('nest_items');
    localStorage.removeItem('nest_messages');
    localStorage.removeItem('nest_preferences');
    localStorage.setItem('nest_onboarding_done', 'false');

    // Reset local component references
    setOnboardingDoneState(false);
    setItems(INITIAL_ITEMS);
    setSpaces(INITIAL_SPACES);
    setMessages(INITIAL_MESSAGES);
    setPreferences(DEFAULT_PREFERENCES);
    setActiveTab('智能面板');
  };

  // Onboarding View bypass if false
  if (!onboardingDone) {
    return (
      <OnboardingView onComplete={handleOnboardingComplete} />
    );
  }

  // Count severe warning notifications to display on persistent alert ticker
  const urgentCount = items.filter(i => i.tag === '告急' || i.tag === '过期预警').length;
  const recentExpiryTitle = items.find(i => i.tag === '告急' || i.tag === '过期预警')?.title || '面包等';

  return (
    <div className="min-h-screen bg-background text-on-surface font-sans flex flex-col relative pb-8">
      
      {/* Dynamic Slide Banner Notification */}
      {notification && (
        <div className="fixed top-4 left-1/2 transform -translate-x-1/2 z-50 bg-on-surface text-white px-6 py-3 rounded-full border-2 border-primary shadow-[4px_4px_0px_0px_#1b1c1c] text-xs font-black animate-bounce flex items-center gap-2">
          <span>🐿️</span>
          <span>{notification}</span>
        </div>
      )}

      {/* Persistent global alert ticker at very top */}
      <div className="w-full bg-error text-white border-b-2 border-on-surface py-2.5 px-4 text-center text-xs font-extrabold flex items-center justify-center gap-2 select-none shadow-[0px_3px_0px_0px_#1b1c1c]">
        <Bell className="w-4 h-4 animate-shake fill-current" />
        <span>
          {urgentCount > 0 
            ? `今日松鼠播报：巢里有 ${urgentCount} 件食材物资告急中！${recentExpiryTitle} 已经快见底/过期临界区，请及时用闪电录入或点击厨房一键标记食用哦！`
            : "今日松鼠播报：洞中囤藏物资满载很安定，筑巢小助手运行顺利！继续保持优秀整理习惯～"}
        </span>
      </div>

      {/* Main visual header wrapper */}
      <header className="py-6 px-6 md:px-12 max-w-6xl w-full mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
        
        {/* Playful Brand Logo */}
        <div className="flex items-center gap-2">
          <div className="bg-primary text-white p-2.5 rounded-2xl border-2 border-on-surface shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] rotate-[-1deg]">
            <span className="text-3xl">🏡</span>
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-headline-lg font-black text-on-surface leading-none flex items-center gap-1.5" id="app_title">
              <span>松鼠筑巢</span>
              <span className="text-xs bg-secondary-container text-on-secondary-container px-2 py-0.5 rounded-full border border-on-surface">智能生活管家</span>
            </h1>
            <p className="text-[11px] text-on-surface-variant font-black tracking-wide mt-1">SQUIRREL'S NEST · ORGANIZED BEAUTIFULLY</p>
          </div>
        </div>

        {/* Tab Navigator */}
        <nav className="flex flex-wrap gap-2 md:gap-3 bg-white border-2 border-on-surface px-3 py-2 rounded-full shadow-[3px_3px_0px_0px_rgba(27,28,28,1)]" id="main_tabs">
          {[
            { id: '智能面板', icon: <Home className="w-4 h-4" /> },
            { id: '松鼠助手', icon: <MessageCircle className="w-4 h-4" /> },
            { id: '库存管理', icon: <Archive className="w-4 h-4" /> },
            { id: '参数设定', icon: <Settings className="w-4 h-4" /> },
          ].map((tab) => {
            const isSelected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2 text-xs font-black rounded-full border-2 transition-all cursor-pointer ${
                  isSelected 
                    ? 'bg-primary text-white border-on-surface shadow-[1px_1px_0px_0px_rgba(0,0,0,1)] scale-[1.01] -rotate-1' 
                    : 'bg-transparent border-transparent hover:border-on-surface hover:bg-surface-container-low'
                }`}
                id={`tab-${tab.id}`}
              >
                {tab.icon}
                <span>{tab.id}</span>
              </button>
            );
          })}
        </nav>

        {/* Diagnostic reboarding shortcut button */}
        <div className="hidden sm:block">
          <button
            onClick={() => {
              if (confirm("想重新进入设置向导对生活习惯或物理仓库格数进行重新绘制吗？")) {
                setOnboardingDoneState(false);
              }
            }}
            className="text-[10px] bg-white text-on-surface-variant px-3 py-1.5 rounded-full border border-on-surface shadow-[1.5px_1.5px_0px_0px_#000] hover:translate-y-px font-black cursor-pointer"
          >
            ⚙️ 重新绘制空间
          </button>
        </div>
      </header>

      {/* Core Panel Content view */}
      <main className="flex-grow px-6 md:px-12 max-w-6xl w-full mx-auto">
        
        {activeTab === '智能面板' && (
          <DashboardView 
            items={items}
            spaces={spaces}
            preferences={preferences}
            onNavigateToTab={(tab) => {
              setActiveTab(tab);
              // Trigger mini animation alert
              triggerBannerNotification(`已切换到柜子「${tab}」档案视图`);
            }}
            onAddItem={handleAddItem}
            onConsumeItem={handleConsumeItem}
            onDiscardItem={handleDeleteItem}
          />
        )}

        {activeTab === '松鼠助手' && (
          <AssistantView 
            messages={messages}
            items={items}
            spaces={spaces}
            onSendMessage={handleSendChatMessage}
            onReceiveAIResponse={handleReceiveAIResponse}
            onAddItem={handleAddItem}
          />
        )}

        {activeTab === '库存管理' && (
          <InventoryView 
            items={items}
            spaces={spaces}
            onUpdateItem={handleUpdateItem}
            onDeleteItem={handleDeleteItem}
            onAddItem={handleAddItem}
          />
        )}

        {activeTab === '参数设定' && (
          <SettingsView 
            preferences={preferences}
            onSavePreferences={handleSavePreferences}
            onResetAllData={handleResetAllData}
          />
        )}

      </main>

      {/* Styled doodle footer banner */}
      <footer className="mt-16 border-t-2 border-on-surface py-6 px-6 md:px-12 max-w-6xl w-full mx-auto flex flex-col sm:flex-row justify-between items-center text-xs text-on-surface-variant font-bold gap-4 select-none">
        <div>🏡 松鼠筑巢 — 治愈感智能家居收纳理账管家</div>
        <div className="flex gap-4">
          <span className="flex items-center gap-1">💖 组织让生活更优雅</span>
          <span>·</span>
          <span>离线安全协议</span>
        </div>
      </footer>

    </div>
  );
}
