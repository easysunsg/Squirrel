import React, { useState, useRef, useEffect } from 'react';
import { Message, Item, Space } from '../types';
import { Send, Sparkles, Mic, BarChart2, PlusCircle, CheckCircle, Image, User, Volume2, HelpCircle, Archive, Edit } from 'lucide-react';

interface AssistantViewProps {
  messages: Message[];
  items: Item[];
  spaces: Space[];
  onSendMessage: (message: Message) => void;
  onReceiveAIResponse: (replyText: string, cardData: any) => void;
  onAddItem: (item: Partial<Item>) => void;
}

export default function AssistantView({
  messages,
  items,
  spaces,
  onSendMessage,
  onReceiveAIResponse,
  onAddItem
}: AssistantViewProps) {
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // History list state
  const [historyList, setHistoryList] = useState([
    { id: 'h1', title: '帮我整理储藏间箱子', date: '今天' },
    { id: 'h2', title: '寻找丢失的螺丝刀分类', date: '昨天' },
    { id: 'h3', title: '列出所有过期的调料列表', date: '前天' },
  ]);

  const suggestions = [
    { text: '🔍 寻找损坏的五金工具箱在哪', role: 'search' },
    { text: '📦 将6个全麦面包存入厨房', role: 'ingest' },
    { text: '🧹 帮我拟定一份厨房整理清单', role: 'agenda' },
  ];

  // Auto-scroll to end of thread
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSend = async (textToSend: string) => {
    if (!textToSend.trim()) return;

    // Send original user message
    const userMsg: Message = {
      id: 'usr-' + Date.now(),
      sender: 'user',
      text: textToSend,
      timestamp: '刚刚',
      type: 'text'
    };

    onSendMessage(userMsg);
    setInputText('');
    setIsTyping(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chatHistory: [...messages, userMsg],
          currentInventory: items
        })
      });
      const data = await response.json();
      onReceiveAIResponse(data.text, data.cardData);
    } catch (e) {
      console.error(e);
      // Fallback
      setTimeout(() => {
        onReceiveAIResponse(
          "松鼠正钻出洞来寻找你的备忘录～ 看来连接太远啦！不过小松鼠在你的储藏柜旁边做了备注哦 🐿️", 
          null
        );
      }, 1000);
    } finally {
      setIsTyping(false);
    }
  };

  const handleInjestConfirmed = (card: any, msgId: string) => {
    // Add real item to state!
    onAddItem({
      title: card.title,
      spaceId: card.spaceName === '车库工具' ? 'garage' : (card.spaceName === '储藏间' ? 'storage' : 'kitchen'),
      spaceName: card.spaceName,
      location: card.spaceName === '车库工具' ? '车库 B4 工具箱' : '厨房二级柜',
      remainingPct: 100,
      count: card.quantity || 1,
      unit: '件',
      tag: '充足',
      icon: card.spaceName === '车库工具' ? 'construction' : 'kitchen',
      remark: '经AI松鼠助手语音分类录入确认。'
    });

    alert(`🎉 恭喜！【${card.title}x${card.quantity}】已经成功放入【${card.spaceName}】洞空间库存中！🐿️`);
  };

  // Sound play simulation widget
  const togglePlayVoice = (id: string) => {
    if (playingVoiceId === id) {
      setPlayingVoiceId(null);
    } else {
      setPlayingVoiceId(id);
      setTimeout(() => {
        setPlayingVoiceId(null);
      }, 4000);
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 border-2 border-on-surface rounded-2xl overflow-hidden bg-white mt-4 h-[calc(100vh-160px)] shadow-[6px_6px_0px_0px_rgba(27,28,28,1)]">
      
      {/* Left Sidebar Menu: History Chat Records */}
      <div className="md:col-span-1 bg-surface-container-low border-r-2 border-on-surface flex flex-col p-4 select-none">
        <button 
          onClick={() => {
            alert("正在清理小松鼠的大脑，准备启动全新对话新纪元啦～");
            // Set simple default
            onReceiveAIResponse("哈喽！新巢开始筑起，有什么想让小松鼠帮你清算登记的物品吗？🐿️", null);
          }}
          className="w-full py-2.5 bg-on-surface text-white rounded-xl border-2 border-on-surface font-extrabold text-sm flex items-center justify-center gap-2 hover:bg-primary shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] active:translate-y-px duration-75 cursor-pointer"
        >
          ➕ 新建对话
        </button>

        <div className="mt-6 flex-grow">
          <h4 className="text-xs font-black text-on-surface-variant uppercase tracking-wider mb-3">最近对话</h4>
          <div className="space-y-2">
            {historyList.map((hist) => (
              <button
                key={hist.id}
                onClick={() => {
                  handleSend(`帮我回顾：${hist.title}`);
                }}
                className="w-full text-left p-3 rounded-lg border border-on-surface/20 hover:border-on-surface hover:bg-white text-xs font-bold text-on-surface truncate block transition-all"
              >
                🌰 {hist.title}
                <span className="block text-[10px] text-on-surface-variant/70 mt-1 font-normal">{hist.date}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Sync memory footer */}
        <div className="p-3 bg-secondary-fixed rounded-xl border border-on-surface text-[10px] text-on-secondary-fixed font-bold leading-relaxed shadow-[1px_1px_0px_0px_#000]">
          🐿️ 小知识：松鼠大脑最多能记住自己在森林里埋藏的200个坚果洞位置哦！比我们更记性好呢！
        </div>
      </div>

      {/* Right Core thread column (3 cols) */}
      <div className="md:col-span-3 flex flex-col h-full bg-surface-container-lowest">
        
        {/* Chat Thread Area */}
        <div className="flex-grow overflow-y-auto p-6 space-y-6 max-h-[calc(100vh-320px)]">
          {messages.map((msg) => {
            const isUser = msg.sender === 'user';
            return (
              <div 
                key={msg.id} 
                className={`flex gap-4 ${isUser ? 'flex-row-reverse' : 'flex-row'} items-start`}
              >
                {/* Avatar */}
                <div className={`w-10 h-10 rounded-full border-2 border-on-surface flex items-center justify-center ${isUser ? 'bg-primary-container text-white' : 'bg-white'} shadow-[2px_2px_0px_0px_rgba(0,0,0,1)]`}>
                  {isUser ? <User className="w-5 h-5" /> : <span className="text-xl">🐿️</span>}
                </div>

                {/* Content Bubble */}
                <div className="max-w-[75%] space-y-2">
                  
                  {/* Speech or raw message */}
                  {msg.type === 'welcome' && (
                    <div className="bg-white border-2 border-on-surface p-4 rounded-2xl shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] relative">
                      <p className="text-sm font-bold text-on-surface leading-relaxed">{msg.text}</p>
                      
                      {/* Styled mascot image inline matching our mock reference */}
                      <img 
                        alt="Squirrel Mascot" 
                        className="w-36 h-36 mx-auto object-contain mt-3 rounded-xl border border-on-surface bg-secondary-fixed" 
                        src="https://lh3.googleusercontent.com/aida-public/AB6AXuDMAAidjrmASOkbCLEtGD5zGevPayzGKg2VP3CbkzCKCZHsxBGlDCpIlmAhc-D4A02_riCI9fqyEy-ACO9vXjni6FlsWpkLvupK056lUz8I8QfBFK9VFaOVzdDyUoJh4_ki0W7CUDyV-h4PIzKJSQSzfsKlNb1XZ9OkpMZxqQIPm3xqAdx_hIyRWaavvbh0-7mIn7yIl3Rj2xlzQ8iz2lSDwJ9PBSdC0l0Vo3YIPFNb1d_Dr22BpqBDfZ6GpzRt8T3Oy8ABffrucJFL"
                        referrerPolicy="no-referrer"
                      />
                    </div>
                  )}

                  {msg.type === 'text' && (
                    <div className={`border-2 border-on-surface p-3.5 rounded-2xl shadow-[3px_3px_0px_0px_rgba(0,0,0,1)] ${isUser ? 'bg-primary-fixed text-on-primary-fixed' : 'bg-white text-on-surface'} text-sm font-bold leading-relaxed`}>
                      {msg.text}
                    </div>
                  )}

                  {msg.type === 'voice' && (
                    <div 
                      onClick={() => togglePlayVoice(msg.id)}
                      className="border-2 border-on-surface bg-white p-3 rounded-2xl shadow-[3px_3px_0px_0px_rgba(0,0,0,1)] flex items-center gap-4 cursor-pointer hover:bg-surface-container-low transition-colors"
                    >
                      <div className="bg-primary text-white p-2 rounded-full border border-on-surface">
                        <Volume2 className={`w-4 h-4 ${playingVoiceId === msg.id ? 'animate-bounce' : ''}`} />
                      </div>
                      
                      {/* Interactive sound track visualization bar */}
                      <div className="flex gap-0.5 items-center">
                        {[1, 2, 3, 4, 3, 2, 1, 2, 4, 5, 4, 2, 3, 4, 3, 1, 2, 4, 1].map((val, idx) => {
                          const playHeight = playingVoiceId === msg.id ? (Math.random() * 16 + 4) : (val * 4);
                          return (
                            <div 
                              key={idx} 
                              className="w-0.5 bg-primary rounded-full transition-all" 
                              style={{ height: `${playHeight}px` }} 
                            />
                          );
                        })}
                      </div>

                      <span className="text-xs font-mono font-bold text-on-surface-variant">
                        {msg.voiceDuration || '0:12'}
                      </span>
                    </div>
                  )}

                  {/* Structured AI Ingestion Confirmation Card matching mockup 3 */}
                  {msg.type === 'action_card' && msg.actionCard && (
                    <div className="space-y-3">
                      <div className="bg-white border-2 border-on-surface p-3 rounded-2xl shadow-[3px_3px_0px_0px_rgba(0,0,0,1)] text-sm font-bold text-on-surface leading-relaxed">
                        {msg.text}
                      </div>

                      <div className="bg-white border-2 border-on-surface p-4 rounded-xl shadow-[4px_4px_0px_0px_#1b1c1c] max-w-sm">
                        <img 
                          alt="Ingesting asset" 
                          className="w-full h-32 object-cover rounded-lg border border-on-surface mb-3" 
                          src={msg.actionCard.image}
                          referrerPolicy="no-referrer"
                        />
                        <div className="flex justify-between items-center mb-2">
                          <h4 className="font-extrabold text-base text-on-surface">{msg.actionCard.title}</h4>
                          <span className="bg-error-container text-error text-[10px] font-black px-2 py-0.5 rounded-full border border-on-surface">待分类</span>
                        </div>
                        <div className="flex gap-2 text-xs font-bold text-on-surface-variant mb-4">
                          <span>数量: {msg.actionCard.quantity}</span>
                          <span>·</span>
                          <span>空间: {msg.actionCard.spaceName}</span>
                        </div>
                        
                        <div className="grid grid-cols-2 gap-2">
                          <button 
                            onClick={() => handleInjestConfirmed(msg.actionCard, msg.id)}
                            className="bg-primary text-white py-2 rounded-lg font-bold text-xs border border-on-surface shadow-[1px_1px_0px_0px_#000] hover:translate-y-px duration-75 cursor-pointer text-center"
                          >
                            确认入库
                          </button>
                          <button 
                            onClick={() => {
                              const typed = prompt("请输入您想修改的物品名称：", msg.actionCard?.title);
                              if (typed) {
                                alert(`已修改信息：【${typed}】，请再次确认入库！🥞`);
                              }
                            }}
                            className="bg-white text-on-surface py-2 rounded-lg font-bold text-xs border border-on-surface shadow-[1px_1px_0px_0px_#000] active:translate-y-px duration-75 cursor-pointer text-center"
                          >
                            修改信息
                          </button>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="text-[10px] text-on-surface-variant font-bold text-right">
                    {msg.timestamp}
                  </div>
                </div>

              </div>
            );
          })}

          {isTyping && (
            <div className="flex items-center gap-2 text-xs font-bold text-on-surface-variant bg-white border border-on-surface px-4 py-2 rounded-full w-max animate-pulse">
              <span>🐿️ 小松鼠管家正在寻找并分类中...</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Suggestion pill badges */}
        <div className="px-6 py-2 flex flex-wrap gap-2 border-t border-on-surface/10 bg-white select-none">
          {suggestions.map((sug, i) => (
            <button
              key={i}
              onClick={() => {
                setInputText(sug.text);
                handleSend(sug.text);
              }}
              className="text-xs font-bold bg-secondary-fixed text-on-secondary-fixed px-3 py-1.5 rounded-full border-2 border-on-surface shadow-[2px_2px_0px_0px_#000] hover:translate-x-px duration-75 cursor-pointer"
            >
              {sug.text}
            </button>
          ))}
        </div>

        {/* Entry Zone bottom bar */}
        <div className="p-4 border-t-2 border-on-surface bg-white flex items-center gap-3">
          <button 
            onClick={() => {
              const speakText = prompt("模拟语音录入 (输入你想吩咐松鼠说的语音词)：", "帮我看一下工具箱里的螺丝刀还在不");
              if (speakText) {
                const voiceMsg: Message = {
                  id: 'voice-' + Date.now(),
                  sender: 'user',
                  text: `[语音消息: ${speakText}]`,
                  timestamp: '刚刚',
                  type: 'voice',
                  voiceDuration: '0:06'
                };
                onSendMessage(voiceMsg);
                handleSend(speakText);
              }
            }}
            className="p-3 bg-secondary-fixed text-on-secondary-fixed rounded-xl border-2 border-on-surface shadow-[2px_2px_0px_0px_#000] active:translate-y-px cursor-pointer" 
            title="点击模拟麦克风进行语音录入录音"
          >
            <Mic className="w-5 h-5" />
          </button>
          
          <input 
            type="text" 
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSend(inputText);
            }}
            placeholder="输入想要吩咐的事情，比如『家里还有面包吗』或『存入洗洁精2瓶』..." 
            className="flex-grow border-2 border-on-surface p-3 rounded-xl font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 text-sm"
          />

          <button 
            onClick={() => handleSend(inputText)}
            disabled={!inputText.trim()}
            className="p-3 bg-primary text-white rounded-xl border-2 border-on-surface shadow-[2px_2px_0px_0px_#000] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            <Send className="w-5 h-5 fill-current" />
          </button>
        </div>

      </div>

    </div>
  );
}
