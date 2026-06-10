import React, { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Send, Trash2, Plus, Sparkles, MessageSquare } from "lucide-react";
import { AppSettings, ChatMessage, InventoryItem } from "../types";

interface ChatProps {
  settings: AppSettings;
  items: InventoryItem[];
  preinput: string;
  onClearPreinput: () => void;
  onSaveNewItem: (item: InventoryItem) => void;
  onSendMessage: (text: string) => Promise<void> | void;
  onAppendLocalMessage: (message: ChatMessage) => void;
  onClearChatHistory: () => void;
  messages: ChatMessage[];
  isSendingMessage: boolean;
  chatError?: string | null;
}

export const ChatTab: React.FC<ChatProps> = ({
  settings,
  items,
  preinput,
  onClearPreinput,
  onSaveNewItem,
  onSendMessage,
  onAppendLocalMessage,
  onClearChatHistory,
  messages,
  isSendingMessage,
  chatError,
}) => {
  const [inputText, setInputText] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (preinput) {
      setInputText(preinput);
      onClearPreinput();
    }
  }, [onClearPreinput, preinput]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const createMessage = (sender: ChatMessage["sender"], text: string): ChatMessage => ({
    id: `msg-${sender}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    sender,
    text,
    timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  });

  const handleSend = () => {
    const text = inputText.trim();
    if (!text || isSendingMessage) {
      return;
    }

    setInputText("");
    void onSendMessage(text);
  };

  const handleInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) {
      return;
    }

    event.preventDefault();
    handleSend();
  };

  const handleQuickAdd = () => {
    const today = new Date();
    const expiry = new Date(today);
    expiry.setDate(today.getDate() + 7);

    onSaveNewItem({
      id: `item-${Date.now()}`,
      name: "新鲜番茄",
      category: "food",
      quantity: 3,
      unit: "个",
      location: settings.selectedLocations[0] || "主冰箱",
      purchaseDate: today.toISOString().slice(0, 10),
      expiryDate: expiry.toISOString().slice(0, 10),
      remindDaysBefore: 3,
      tags: [settings.lifestyleTag, "手动快捷添加"],
      note: "从聊天页快捷添加的测试物品",
    });

    onAppendLocalMessage(createMessage("assistant", "已帮你快捷添加一条「新鲜番茄」到库存。"));
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
      <section className="lg:col-span-3 bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] min-h-[640px] flex flex-col overflow-hidden">
        <div className="p-4 border-b-2 border-on-background flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <MessageSquare className="text-primary" size={22} />
            <div>
              <h2 className="font-display font-extrabold text-lg text-on-background">松鼠聊天</h2>
              <p className="text-xs text-outline">生活标签：{settings.lifestyleTag}，提醒时间：{settings.reminderTime}</p>
            </div>
          </div>
          <button
            onClick={onClearChatHistory}
            className="p-2 border-2 border-on-background rounded-xl bg-surface hover:bg-red-50 active-press-sm"
            title="清空聊天"
          >
            <Trash2 size={16} className="text-red-600" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-surface-container-low">
          {messages.length === 0 ? (
            <div className="h-full min-h-[360px] flex items-center justify-center text-center text-outline text-sm">
              暂无聊天记录，输入一句话开始整理。
            </div>
          ) : (
            messages.map((message) => {
              const isUser = message.sender === "user";
              return (
                <motion.div
                  key={message.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`flex ${isUser ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[82%] border-2 border-on-background rounded-2xl px-4 py-3 text-sm shadow-[2px_3px_0_0_#1b1c1c] ${
                      isUser ? "bg-primary text-white" : "bg-white text-on-background"
                    }`}
                  >
                    <p className="leading-relaxed whitespace-pre-wrap">{message.text}</p>
                    <div className={`text-[10px] mt-2 ${isUser ? "text-white/70" : "text-outline"}`}>
                      {message.timestamp}
                    </div>
                  </div>
                </motion.div>
              );
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="p-4 border-t-2 border-on-background bg-white space-y-2">
          {chatError && (
            <div className="rounded-xl border-2 border-orange-300 bg-orange-50 px-3 py-2 text-xs font-medium text-orange-700">
              {chatError}
            </div>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleInputKeyDown}
              disabled={isSendingMessage}
              placeholder="输入库存、收纳或临期提醒问题..."
              className="flex-1 p-3 border-2 border-on-background rounded-xl bg-surface text-sm focus:bg-white focus:outline-none disabled:opacity-60"
            />
            <button
              onClick={handleSend}
              disabled={!inputText.trim() || isSendingMessage}
              className="px-4 bg-primary text-white border-2 border-on-background rounded-xl hover:bg-opacity-95 active-press disabled:opacity-50 disabled:pointer-events-none"
              title="发送"
            >
              {isSendingMessage ? <span className="text-xs font-bold">发送中</span> : <Send size={18} />}
            </button>
          </div>
        </div>
      </section>

      <aside className="bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-4 h-fit space-y-4">
        <div className="flex items-center gap-2">
          <Sparkles className="text-tertiary" size={18} />
          <h3 className="font-display font-extrabold text-sm text-on-background">快捷动作</h3>
        </div>

        <button
          onClick={() => setInputText("帮我检查一下今天哪些库存需要优先处理。")}
          className="w-full text-left p-3 border-2 border-on-background rounded-xl bg-surface hover:bg-[#ffe92e] active-press-sm text-xs font-medium"
        >
          检查今日库存
        </button>
        <button
          onClick={() => setInputText(`按照「${settings.lifestyleTag}」推荐一个消耗临期食材的方案。`)}
          className="w-full text-left p-3 border-2 border-on-background rounded-xl bg-surface hover:bg-[#ffe92e] active-press-sm text-xs font-medium"
        >
          推荐临期处理方案
        </button>
        <button
          onClick={handleQuickAdd}
          className="w-full flex items-center justify-center gap-2 p-3 border-2 border-on-background rounded-xl bg-secondary text-white active-press text-xs font-bold"
        >
          <Plus size={15} /> 快捷添加示例物品
        </button>
      </aside>
    </div>
  );
};
