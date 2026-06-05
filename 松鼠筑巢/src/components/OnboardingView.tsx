import React, { useState } from 'react';
import { Space, SystemPreferences } from '../types';
import { Sparkles, ArrowRight, ArrowLeft, Check, HelpCircle, AlertTriangle, Play, HelpCircle as HelpIcon, Flame, Bell, Trash2 } from 'lucide-react';

interface OnboardingViewProps {
  onComplete: (preferences: Partial<SystemPreferences>, selectedSpaces: string[]) => void;
}

export default function OnboardingView({ onComplete }: OnboardingViewProps) {
  const [step, setStep] = useState<number>(1);
  const [spaces, setSpaces] = useState<string[]>(['主冰箱']);
  const [allergies, setAllergies] = useState<string[]>(['乳制品']);
  const [lifestyle, setLifestyle] = useState<string>('极简主义');
  const [shelfStrategy, setShelfStrategy] = useState<number>(30); // 0 Strict - 100 Flexible
  const [reminderTime, setReminderTime] = useState<string>('19:30');
  const [showSuccess, setShowSuccess] = useState<boolean>(false);
  
  // Custom new space input
  const [newSpaceInput, setNewSpaceInput] = useState<string>('');
  const [showAddSpace, setShowAddSpace] = useState<boolean>(false);

  const availableSpaces = [
    { name: '主冰箱', icon: 'Refrigerator' },
    { name: '厨房储物柜', icon: 'Cabinet' },
    { name: '玄关柜', icon: 'Door' },
    { name: '药箱', icon: 'FirstAid' },
    { name: '化妆台', icon: 'Smile' },
  ];

  const toggleSpace = (name: string) => {
    if (spaces.includes(name)) {
      setSpaces(spaces.filter(s => s !== name));
    } else {
      setSpaces([...spaces, name]);
    }
  };

  const toggleAllergy = (name: string) => {
    if (allergies.includes(name)) {
      setAllergies(allergies.filter(a => a !== name));
    } else {
      setAllergies([...allergies, name]);
    }
  };

  const handleAddNewSpace = () => {
    if (newSpaceInput.trim()) {
      if (!spaces.includes(newSpaceInput.trim())) {
        setSpaces([...spaces, newSpaceInput.trim()]);
      }
      setNewSpaceInput('');
      setShowAddSpace(false);
    }
  };

  const handleComplete = () => {
    handleFinalSubmit();
  };

  const handleFinalSubmit = () => {
    onComplete({
      allergies,
      lifestyle,
      warningThreshold: shelfStrategy < 30 ? 3 : (shelfStrategy < 70 ? 5 : 7),
      lowThreshold: shelfStrategy < 30 ? 10 : (shelfStrategy < 70 ? 15 : 20),
      reminderTime
    }, spaces);
  };

  // Fun little CSS confetti simulator
  const renderConfetti = () => {
    if (!showSuccess) return null;
    return (
      <div className="absolute inset-0 overflow-hidden pointer-events-none z-50">
        {[...Array(40)].map((_, i) => {
          const colors = ['#b70052', '#006e1c', '#f9e534', '#dd2269'];
          const randomColor = colors[Math.floor(Math.random() * colors.length)];
          const style = {
            backgroundColor: randomColor,
            left: `${Math.random() * 100}%`,
            top: `-20px`,
            transform: `rotate(${Math.random() * 360}deg)`,
            animation: `fall ${Math.random() * 2 + 1.5}s linear forwards`
          };
          return (
            <div 
              key={i} 
              className="absolute w-2.5 h-2.5 rounded-xs" 
              style={style} 
            />
          );
        })}
        <style dangerouslySetInnerHTML={{ __html: `
          @keyframes fall {
            0% { top: -20px; opacity: 1; transform: rotate(0deg) translateY(0); }
            100% { top: 100%; opacity: 0; transform: rotate(720deg) translateY(100px); }
          }
        `}} />
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-tertiary-fixed text-on-surface font-sans flex flex-col p-6 md:p-12 relative overflow-x-hidden select-none">
      
      {/* Top Header Navigation for Onboarding branding */}
      <header className="flex justify-between items-center w-full mb-12 max-w-4xl mx-auto">
        <div className="bg-primary-container border-2 border-on-surface px-6 py-2 rounded-full rotate-[-1deg] shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] flex items-center gap-2">
          <span className="font-headline-lg text-headline-lg font-black text-on-primary-container text-2xl" id="onboarding_brand">松鼠筑巢</span>
          <span className="bg-white/20 p-1 rounded-full text-white text-xs">🐿️ 筑巢策略</span>
        </div>
        <div className="hidden md:flex gap-4">
          <div className="bg-white pointer-events-auto border-2 border-on-surface p-2 rounded-full hover:scale-105 active:scale-95 transition-all shadow-[2px_2px_0px_0px_rgba(27,28,28,1)] cursor-pointer">
            <HelpCircle className="w-5 h-5 text-on-surface" />
          </div>
        </div>
      </header>

      {/* Main setup wizard body */}
      <main className="flex-grow flex items-center justify-center relative w-full max-w-4xl mx-auto">
        
        {/* Floating background decorations */}
        <div className="absolute -top-10 -left-10 md:left-4 animate-bounce opacity-40 md:opacity-75 select-none hidden sm:block">
          <div className="bg-secondary-container border-2 border-on-surface p-4 rounded-xl rotate-12 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
            <span className="text-4xl text-on-surface">🥦</span>
          </div>
        </div>
        <div className="absolute -bottom-10 -right-10 md:right-4 animate-pulse opacity-40 md:opacity-75 select-none hidden sm:block">
          <div className="bg-primary-fixed border-2 border-on-surface p-4 rounded-xl -rotate-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
            <span className="text-4xl text-on-surface">📻</span>
          </div>
        </div>

        {/* Outer content panel card */}
        <div className="bg-background w-full max-w-2xl border-2 border-on-surface p-8 md:p-12 relative overflow-hidden z-10 rounded-2xl shadow-[6px_6px_0px_0px_rgba(27,28,28,1)]">
          {renderConfetti()}

          {/* If success complete setup wizard screen is displayed */}
          {showSuccess ? (
            <div className="absolute inset-0 bg-secondary-container flex flex-col items-center justify-center p-8 text-center" id="success-screen">
              <div className="bg-white p-6 rounded-full border-4 border-on-surface mb-6 animate-bounce shadow-[3px_3px_0px_0px_#1b1c1c]">
                <Check className="w-16 h-16 text-secondary stroke-[3]" />
              </div>
              <h2 className="text-3xl md:text-4xl font-headline-lg font-black text-on-surface mb-4">准备就绪！</h2>
              <p className="text-lg text-on-secondary-container font-medium mb-8 max-w-md">
                您的智能筑巢系统已激活。可爱的小松鼠管家正在开往您的首批洞空间，进行首次日常清点。
              </p>
              <button 
                className="bg-on-surface text-white px-12 py-4 rounded-full font-headline-lg text-lg shadow-[6px_6px_0px_0px_rgba(183,0,82,1)] hover:translate-x-0.5 hover:translate-y-0.5 hover:shadow-[4px_4px_0px_0px_rgba(183,0,82,1)] active:translate-y-1 active:translate-x-1 active:shadow-none transition-all cursor-pointer font-bold"
                onClick={handleFinalSubmit}
                id="enter_dashboard_btn"
              >
                进入仪表盘
              </button>
            </div>
          ) : null}

          {/* Tab Progress Dot indicators */}
          <div className="flex gap-2 mb-8 justify-center">
            <div className={`w-12 h-3.5 border-2 border-on-surface rounded-full transition-all duration-300 ${step >= 1 ? 'bg-primary' : 'bg-white'}`} />
            <div className={`w-12 h-3.5 border-2 border-on-surface rounded-full transition-all duration-300 ${step >= 2 ? 'bg-primary' : 'bg-white'}`} />
            <div className={`w-12 h-3.5 border-2 border-on-surface rounded-full transition-all duration-300 ${step >= 3 ? 'bg-primary' : 'bg-white'}`} />
          </div>

          {/* STEP 1: Space Planning */}
          {step === 1 && (
            <section className="space-y-6 animate-in fade-in zoom-in-95 duration-200">
              <div className="mb-4">
                <h1 className="text-2xl md:text-3xl font-headline-lg font-bold mb-2">欢迎来到松鼠的小窝!</h1>
                <p className="text-base text-on-surface-variant">首先，我们需要知道您的筑巢蓝图。您想在哪些地方进行整理？</p>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-8">
                {availableSpaces.map((item) => {
                  const isChecked = spaces.includes(item.name);
                  return (
                    <button
                      key={item.name}
                      onClick={() => toggleSpace(item.name)}
                      className={`border-2 border-on-surface p-4 rounded-xl transition-all text-center flex flex-col items-center gap-2 cursor-pointer ${
                        isChecked 
                          ? 'bg-secondary-container shadow-[2px_2px_0px_0px_#1b1c1c] translate-y-0.5 font-bold' 
                          : 'bg-white hover:scale-[1.02] active:scale-95 shadow-[4px_4px_0px_0px_#1b1c1c]'
                      }`}
                    >
                      <span className="text-3xl">
                        {item.name === '主冰箱' ? '🥛' : 
                         item.name === '厨房储物柜' ? '🍜' : 
                         item.name === '玄关柜' ? '👟' : 
                         item.name === '药箱' ? '💊' : '💄'}
                      </span>
                      <span className="text-sm font-semibold">{item.name}</span>
                    </button>
                  );
                })}

                {/* Additional spaces custom mapper button */}
                {showAddSpace ? (
                  <div className="border-2 border-on-surface p-3 bg-white rounded-xl flex flex-col gap-2 shadow-[2px_2px_0px_0px_#1b1c1c]">
                    <input
                      type="text"
                      placeholder="空间名"
                      className="border-2 border-on-surface py-1 px-2 rounded-lg text-xs w-full focus:outline-none"
                      value={newSpaceInput}
                      onChange={(e) => setNewSpaceInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleAddNewSpace();
                      }}
                    />
                    <div className="flex gap-1 justify-end">
                      <button 
                        onClick={() => setShowAddSpace(false)} 
                        className="text-[10px] text-on-surface-variant hover:underline"
                      >
                        取消
                      </button>
                      <button 
                        onClick={handleAddNewSpace} 
                        className="text-[10px] font-bold text-primary hover:underline"
                      >
                        确定
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowAddSpace(true)}
                    className="bg-surface-container-high border-2 border-on-surface border-dashed p-4 rounded-xl flex flex-col items-center justify-center gap-2 opacity-70 hover:opacity-100 transition-opacity cursor-pointer"
                  >
                    <span className="text-2xl">➕</span>
                    <span className="text-sm font-bold">添加空间</span>
                  </button>
                )}
              </div>

              {/* Added active space badges summary indicator */}
              <div className="p-3 bg-surface-container-low rounded-xl border border-on-surface text-xs text-on-surface-variant">
                <span className="font-bold text-primary">已选择的初始筑巢空间：</span>
                {spaces.length === 0 ? '还没有勾选哦。' : spaces.join('、')}
              </div>

              <div className="flex justify-end pt-4">
                <button 
                  className="bg-primary text-on-primary px-8 py-3 rounded-full font-bold flex items-center gap-1.5 border-2 border-on-surface shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] hover:translate-x-0.5 hover:translate-y-0.5 hover:shadow-[2px_2px_0px_0px_#1b1c1c] active:translate-y-1 active:translate-x-1 active:shadow-none transition-all cursor-pointer"
                  onClick={() => setStep(2)}
                >
                  下一步 <ArrowRight className="w-5 h-5" />
                </button>
              </div>
            </section>
          )}

          {/* STEP 2: Preferences */}
          {step === 2 && (
            <section className="space-y-6 animate-in fade-in zoom-in-95 duration-200">
              <div>
                <h1 className="text-2xl md:text-3xl font-headline-lg font-bold mb-2">筑巢主人生活习惯</h1>
                <p className="text-base text-on-surface-variant">告诉小松鼠您的日常生活偏好，我们会更智能地推荐食谱与消耗提醒哦。</p>
              </div>

              <div className="space-y-6">
                {/* Allergy Tags */}
                <div>
                  <h3 className="font-bold flex items-center gap-1 text-sm text-primary mb-3">
                    🥛 忌口与过敏 (多选)
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {['海鲜', '花生', '乳制品', '麸质', '大蒜', '纯素食'].map((item) => {
                      const isSelected = allergies.includes(item);
                      return (
                        <button
                          key={item}
                          onClick={() => toggleAllergy(item)}
                          className={`px-4 py-2 border-2 border-on-surface rounded-full text-sm font-semibold transition-all cursor-pointer ${
                            isSelected 
                              ? 'bg-primary-container text-white shadow-[1px_1px_0px_0px_#1b1c1c]' 
                              : 'bg-white hover:bg-primary-fixed-dim'
                          }`}
                        >
                          {item}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Lifestyle selector */}
                <div>
                  <h3 className="font-bold flex items-center gap-1 text-sm text-secondary mb-3">
                    🏃 生活定位
                  </h3>
                  <div className="grid grid-cols-3 gap-3">
                    {['极简主义', '囤货达人', '减脂增肌中'].map((label) => {
                      const isSelected = lifestyle === label;
                      return (
                        <button
                          key={label}
                          onClick={() => setLifestyle(label)}
                          className={`p-3 border-2 border-on-surface rounded-xl text-center font-bold text-xs transition-all cursor-pointer ${
                            isSelected 
                              ? 'bg-tertiary-fixed shadow-[1px_1px_0px_0px_#1b1c1c] scale-98 rotate-1' 
                              : 'bg-white hover:bg-surface-container-low'
                          }`}
                        >
                          {label === '极简主义' ? '🍃 极简主义' : label === '囤货达人' ? '📦 囤货达人' : '💪 减脂增肌'}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>

              <div className="flex justify-between pt-6">
                <button 
                  className="bg-white text-on-surface px-6 py-2.5 rounded-full font-bold border-2 border-on-surface shadow-[2px_2px_0px_0px_rgba(27,28,28,1)] hover:translate-y-0.5 hover:translate-x-0.5 active:translate-y-1 active:shadow-none transition-all cursor-pointer"
                  onClick={() => setStep(1)}
                >
                  返回
                </button>
                <button 
                  className="bg-primary text-on-primary px-8 py-2.5 rounded-full font-bold flex items-center gap-1 border-2 border-on-surface shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] hover:translate-y-0.5 hover:shadow-[2px_2px_0px_0px_#1b1c1c] active:translate-y-1 active:shadow-none transition-all cursor-pointer"
                  onClick={() => setStep(3)}
                >
                  快好了！ <ArrowRight className="w-5 h-5" />
                </button>
              </div>
            </section>
          )}

          {/* STEP 3: Strategies */}
          {step === 3 && (
            <section className="space-y-6 animate-in fade-in zoom-in-95 duration-200">
              <div>
                <h1 className="text-2xl md:text-3xl font-headline-lg font-bold mb-2">最后策略冲刺！</h1>
                <p className="text-base text-on-surface-variant">策略设定关系到保质期紧急变色策略，剩下的交给小松鼠。</p>
              </div>

              <div className="space-y-6">
                {/* Preservation strictness range slider */}
                <div className="bg-secondary-fixed p-5 rounded-2xl border-2 border-on-surface rotate-[-0.5deg]">
                  <h3 className="font-bold text-sm mb-3 flex items-center gap-1.5">
                    ⏳ 保质期预警激进偏好
                  </h3>
                  
                  {/* Slider mimic */}
                  <input 
                    type="range" 
                    min="10" 
                    max="90" 
                    className="w-full h-3 bg-white border-2 border-on-surface rounded-full appearance-none cursor-pointer accent-primary"
                    value={shelfStrategy}
                    onChange={(e) => setShelfStrategy(Number(e.target.value))}
                  />
                  <div className="flex justify-between mt-3 text-xs font-bold font-mono">
                    <span className="bg-error-container/80 border border-on-surface px-2 py-0.5 rounded">
                      严格抛弃 (Strict)
                    </span>
                    <span className="bg-white border border-on-surface px-2 py-0.5 rounded">
                      临期问问 (Moderate)
                    </span>
                    <span className="bg-secondary-container/80 border border-on-surface px-2 py-0.5 rounded">
                      没烂照吃 (Flexible)
                    </span>
                  </div>
                </div>

                {/* Daily warning clock */}
                <div className="flex flex-col md:flex-row items-center gap-4">
                  <div className="flex-1 w-full">
                    <h3 className="font-bold text-sm mb-2 flex items-center gap-1 text-primary">
                      ⏰ 每日库存播报时间
                    </h3>
                    <div className="flex gap-2 items-center bg-white border-2 border-on-surface p-3.5 rounded-xl justify-center shadow-[3px_3px_0px_0px_#1b1c1c]">
                      <span className="text-2xl font-black">🕗</span>
                      <input 
                        type="time" 
                        value={reminderTime}
                        onChange={(e) => setReminderTime(e.target.value)}
                        className="font-black text-xl border-none focus:ring-0 bg-transparent inline-block outline-none"
                      />
                    </div>
                  </div>

                  <div className="flex-1 bg-primary-fixed border-2 border-on-surface p-4 rounded-xl rotate-1 text-xs text-on-primary-fixed font-medium">
                    <span className="font-bold block mb-1">💡 小松鼠爱心提示：</span>
                    建议把时间设在傍晚晚餐准备前。小松鼠会提醒您尽快消灭那些刚好快过期、需要消耗的食材哦！
                  </div>
                </div>
              </div>

              <div className="flex justify-between pt-6">
                <button 
                  className="bg-white text-on-surface px-6 py-2.5 rounded-full font-bold border-2 border-on-surface shadow-[2px_2px_0px_0px_rgba(27,28,28,1)] hover:translate-y-0.5 hover:translate-x-0.5 active:translate-y-1 active:shadow-none transition-all cursor-pointer"
                  onClick={() => setStep(2)}
                >
                  返回
                </button>
                <button 
                  className="bg-secondary text-white px-8 py-2.5 rounded-full font-bold flex items-center gap-1.5 border-2 border-on-surface shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] hover:shadow-[2px_2px_0px_0px_#1b1c1c] active:translate-y-1 active:translate-x-1 active:shadow-none transition-all cursor-pointer"
                  onClick={handleComplete}
                  id="onboarding_complete_btn"
                >
                  开启筑巢 🚀
                </button>
              </div>
            </section>
          )}

        </div>
      </main>

      {/* Styled Footer for Onboarding info */}
      <footer className="w-full py-4 mt-8 flex justify-between items-center border-t-2 border-on-surface max-w-4xl mx-auto text-xs text-on-surface-variant font-semibold">
        <div>松鼠筑巢 - 玩转整理</div>
        <div className="flex gap-4">
          <span>隐私政策</span>
          <span>使用条款</span>
          <span>联系我们</span>
        </div>
      </footer>
    </div>
  );
}
