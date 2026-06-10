import React, { useState } from "react";
import { AppSettings, SquirrelPersonality } from "../types";
import { motion, AnimatePresence } from "motion/react";
import {
  Settings, Trash, Plus, Check, Heart, Home,
  Flame, Bell, RotateCcw, AlertTriangle, Sparkles,
  Clock3, Sprout, X
} from "lucide-react";
import { ReminderSettingsPanel } from "./ReminderSettingsPanel";

interface SettingsProps {
  settings: AppSettings;
  onUpdateSettings: (settings: AppSettings) => Promise<void> | void;
  onResetFactoryData: () => void;
}

export const SettingsTab: React.FC<SettingsProps> = ({
  settings,
  onUpdateSettings,
  onResetFactoryData,
}) => {
  const [personality, setPersonality] = useState<SquirrelPersonality>(settings.squirrelPersonality);
  const [strategy, setStrategy] = useState<'normal' | 'strict' | 'relaxed'>(settings.expirationStrategy);
  const [newLocName, setNewLocName] = useState("");
  const [locs, setLocs] = useState<string[]>(settings.selectedLocations);
  const [selectedHabits, setSelectedHabits] = useState<string[]>(settings.dietaryHabits);
  const [lifestyleTag, setLifestyleTag] = useState(settings.lifestyleTag);
  const [reminderTime, setReminderTime] = useState(settings.reminderTime);
  const [isReminderPanelOpen, setIsReminderPanelOpen] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Preset arrays
  const presetHabits = [
    "海鲜过敏 🦐", "无乳糖 🥛", "轻食主义 🥬", "拒绝浪费 🍎",
    "懒人速食 🍜", "零食控 🍫", "素食者 🥗", "辛辣重度 🌶️",
    "按期清理强迫症 🧹"
  ];

  const handleToggleHabit = (name: string) => {
    if (selectedHabits.includes(name)) {
      setSelectedHabits(selectedHabits.filter(h => h !== name));
    } else {
      setSelectedHabits([...selectedHabits, name]);
    }
  };

  const handleAddLoc = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = newLocName.trim();
    if (clean && !locs.includes(clean)) {
      setLocs([...locs, clean]);
      setNewLocName("");
    }
  };

  const handleRemoveLoc = (name: string) => {
    if (locs.length <= 1) {
      alert("吱！请至少保留一个藏宝储蓄处，不然松鼠的果子就没地方放了！");
      return;
    }
    setLocs(locs.filter(l => l !== name));
  };

  const handleSaveSettings = async () => {
    setIsSaving(true);
    setSaveError(null);

    try {
      await onUpdateSettings({
        ...settings,
        squirrelPersonality: personality,
        expirationStrategy: strategy,
        selectedLocations: locs,
        dietaryHabits: selectedHabits,
        lifestyleTag,
        reminderTime,
      });
      setSaveSuccess(true);
      setIsReminderPanelOpen(false);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (error) {
      console.error("Failed to save settings", error);
      setSaveError("设置保存失败，请确认后端服务已启动后重试。");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-7 max-w-4xl mx-auto select-none pb-12">
      
      {/* Title block */}
      <div className="flex items-center gap-3 bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-4">
        <Settings className="text-white bg-primary p-1 rounded-full border-2 border-on-background" size={34} />
        <div>
          <h2 className="font-display font-extrabold text-xl text-on-background">松鼠控制台</h2>
          <p className="text-xs text-outline">统一管理提醒时间、生活标签、预警灵敏度与管家性格</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* Left pane: Personalization & Alarm triggers */}
        <div className="space-y-6">
          
          {/* Personality Card */}
          <div className="bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-4 md:p-5 space-y-4">
            <h3 className="font-display font-extrabold text-[14px] text-on-background flex items-center gap-1.5">
              <Flame className="text-[#0f5c1d]" size={17} />
              <span>松鼠拟真管家性格定制</span>
            </h3>

            <div className="space-y-2">
              {[
                { key: "humorous", emoji: "🌰", title: "幽默松本松 (默认)", desc: "喜欢冷笑话，每两句话必带坚果、树洞的谐音折腾段子吱！" },
                { key: "gabby", emoji: "🦜", title: "博学话痨松", desc: "热情过度，热衷罗列各种超级啰嗦的科学防腐和保存知识。" },
                { key: "gentle", emoji: "🌸", title: "温柔松大姐", desc: "心软宠溺，称呼用户为‘亲爱的小主人’，句句关切温顺无比。" },
                { key: "strict_squirrel", emoji: "🧹", title: "强迫症魔王松", desc: "追求完美，容不得任何塞在角落过期的垃圾，严肃犀利吱！" }
              ].map((p) => (
                <button
                  key={p.key}
                  onClick={() => setPersonality(p.key as SquirrelPersonality)}
                  className={`w-full text-left p-3 border-2 border-on-background rounded-[22px] active-press-sm transition-all flex gap-3 ${
                    personality === p.key 
                      ? "bg-[#98f28d] shadow-[2px_3px_0_0_#1b1c1c] -translate-y-0.5 font-bold" 
                      : "bg-surface text-on-background hover:bg-[#ffe92e]"
                  }`}
                >
                  <span className="text-2xl pt-0.5">{p.emoji}</span>
                  <div>
                    <div className="text-xs md:text-sm text-on-background font-display font-medium">{p.title}</div>
                    <div className="text-[10px] text-outline leading-tight mt-0.5">{p.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Alert trigger options */}
          <div className="bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-4 md:p-5 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-display font-extrabold text-[14px] text-on-background flex items-center gap-1.5">
                  <Bell className="text-primary" size={17} />
                  <span>临保期预警阈分配</span>
                </h3>
                <p className="mt-1 text-[10px] text-outline">提醒策略会结合你的生活标签与每日提醒时间一起生效。</p>
              </div>
              <button
                onClick={() => setIsReminderPanelOpen(true)}
                className="shrink-0 rounded-full border-2 border-on-background bg-[#ffe92e] px-3 py-1.5 text-[10px] font-bold text-on-background shadow-[2px_3px_0_0_#1b1c1c] active-press-sm"
              >
                编辑提醒窗口
              </button>
            </div>

            <div className="rounded-[22px] border-2 border-on-background bg-surface p-3 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] font-bold text-outline flex items-center gap-1">
                    <Sprout size={13} className="text-secondary" /> 生活标签
                  </p>
                  <p className="mt-1 text-sm font-display font-bold text-on-background">{lifestyleTag}</p>
                </div>
                <div className="text-right">
                  <p className="text-[10px] font-bold text-outline flex items-center justify-end gap-1">
                    <Clock3 size={13} className="text-tertiary" /> 每日提醒
                  </p>
                  <p className="mt-1 text-sm font-display font-bold text-on-background">{reminderTime}</p>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {[
                { key: "strict", label: "极致强迫症", tip: "临期10天自动亮红灯" },
                { key: "normal", label: "标准松眼", tip: "临期5天自动量橙灯" },
                { key: "relaxed", label: "大条佛系", tip: "临期2天才开启提醒" }
              ].map((st) => (
                <button
                  key={st.key}
                  onClick={() => setStrategy(st.key as any)}
                  className={`p-3 border-2 border-on-background rounded-[22px] text-center active-press-sm transition-all ${
                    strategy === st.key 
                      ? "bg-[#ffe92e] shadow-[2px_3px_0_0_#1b1c1c] -translate-y-0.5 font-bold text-on-background" 
                      : "bg-surface hover:bg-[#ffe92e]"
                  }`}
                >
                  <div className="text-xs font-display font-medium text-on-background">{st.label}</div>
                  <div className="text-[9px] text-outline mt-1 leading-tight">{st.tip}</div>
                </button>
              ))}
            </div>
          </div>

        </div>

        {/* Right pane: Location configs & Dietary Habits */}
        <div className="space-y-6">
          
          {/* Active Chambers configuration */}
          <div className="bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-4 md:p-5 space-y-3.5">
            <h3 className="font-display font-extrabold text-[14px] text-on-background flex items-center gap-1.5">
              <Home className="text-[#694f54]" size={17} />
              <span>活跃储藏室角落 (树洞映射)</span>
            </h3>

            <div className="space-y-2 max-h-[160px] overflow-y-auto pr-1 scrollbar-hide">
              {locs.map((loc) => (
                <div 
                  key={loc}
                  className="flex items-center justify-between p-2 border-2 border-on-background bg-surface rounded-full text-xs font-display shadow-[1px_2px_0_0_#1b1c1c]"
                >
                  <span className="font-bold text-on-background">📍 {loc}</span>
                  <button
                    onClick={() => handleRemoveLoc(loc)}
                    className="p-1 text-red-500 border border-on-background rounded-full hover:bg-red-50 hover:text-red-600 active-press-sm cursor-pointer bg-white"
                    title="拆解此空腔"
                  >
                    <Trash size={12} />
                  </button>
                </div>
              ))}
            </div>

            <form onSubmit={handleAddLoc} className="flex gap-2">
              <input
                type="text"
                placeholder="扩充新树枝如‘地下酒窖’"
                value={newLocName}
                onChange={(e) => setNewLocName(e.target.value)}
                maxLength={10}
                className="flex-1 p-2 border-[3px] border-on-background rounded-full bg-surface text-xs focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
              <button
                type="submit"
                className="px-3 py-1 bg-[#98f28d] text-on-background border-2 border-on-background rounded-full text-xs font-bold hover:bg-[#c7ffc2] shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer flex items-center gap-1"
              >
                <Plus size={14} /> 拓展
              </button>
            </form>
          </div>

          {/* Allergy / habits configurations */}
          <div className="bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-4 md:p-5 space-y-3">
            <h3 className="font-display font-extrabold text-[14px] text-on-background flex items-center gap-1.5">
              <Heart className="text-[#0f5c1d]" size={17} />
              <span>过敏禁忌与轻食习惯对齐</span>
            </h3>

            <div className="flex flex-wrap gap-1.5 pt-1">
              {presetHabits.map((habit) => {
                const isSelected = selectedHabits.includes(habit);
                return (
                  <button
                    key={habit}
                    onClick={() => handleToggleHabit(habit)}
                    className={`px-3 py-1.5 text-xs border-2 border-on-background rounded-full active-press-sm transition-all font-medium cursor-pointer ${
                      isSelected 
                        ? "bg-[#98f28d] text-on-background shadow-[2px_3px_0_0_#1b1c1c] -translate-y-0.5" 
                        : "bg-surface text-on-background hover:bg-[#ffe92e]"
                    }`}
                  >
                    {habit}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Factory Reset options (DANGER AREA) */}
          <div className="bg-[#ffd5d1] border-[3px] border-red-500 rounded-[28px] p-4 space-y-2.5 shadow-[3px_4px_0_0_#1b1c1c]">
            <div className="flex items-center gap-2 text-red-800">
              <AlertTriangle size={18} className="shrink-0 text-red-600" />
              <span className="font-display font-bold text-xs">松林危机备份 (高级危险区)</span>
            </div>
            <p className="text-[10px] text-red-700 leading-normal">
              点击重置按钮将彻底清除浏览器内缓存的所有收纳存案和习惯档案，松鼠会将小家完美还原到最初状态并重新指引。
            </p>
            <button
              onClick={() => {
                if (confirm("🚨【毁灭警告】您确定要粉碎所有数据，重新让小家变回白纸一张吗？")) {
                  onResetFactoryData();
                }
              }}
              className="flex items-center justify-center gap-1.5 w-full bg-red-600 hover:bg-red-700 text-white border-2 border-on-background text-xs font-bold py-2 px-4 rounded-full shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer font-display"
            >
              <RotateCcw size={14} /> 一键粉碎数据并恢复向导
            </button>
          </div>

        </div>

      </div>

      {/* Reminder preferences window */}
      <AnimatePresence>
        {isReminderPanelOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4"
          >
            <motion.div
              initial={{ opacity: 0, y: 18, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 18, scale: 0.98 }}
              className="w-full max-w-3xl rounded-[30px] border-[3px] border-on-background bg-[#fffdf6] p-5 shadow-[8px_10px_0_0_#1b1c1c]"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[#00731e]">提醒设置窗口</p>
                  <h3 className="mt-1 font-display text-2xl font-extrabold text-on-background">生活标签与提醒时间</h3>
                  <p className="mt-2 text-xs text-outline">
                    在控制台里也能直接修改这两个关键设置，不需要重新进入首次引导。
                  </p>
                </div>
                <button
                  onClick={() => setIsReminderPanelOpen(false)}
                  className="rounded-full border-2 border-on-background bg-white p-2 active-press-sm"
                  aria-label="关闭提醒设置窗口"
                >
                  <X size={16} />
                </button>
              </div>

              <ReminderSettingsPanel
                lifestyleTag={lifestyleTag}
                reminderTime={reminderTime}
                onLifestyleTagChange={setLifestyleTag}
                onReminderTimeChange={setReminderTime}
                variant="modal"
              />

              <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs text-outline">保存全部设置后，新的生活标签和提醒时间会立即同步到系统中。</p>
                <div className="flex gap-2 self-end">
                  <button
                    onClick={() => setIsReminderPanelOpen(false)}
                    className="rounded-full border-2 border-on-background bg-white px-4 py-2 text-xs font-bold text-on-background active-press-sm"
                  >
                    先不改了
                  </button>
                  <button
                    onClick={handleSaveSettings}
                    className="rounded-full border-2 border-on-background bg-primary px-4 py-2 text-xs font-bold text-white shadow-[2px_3px_0_0_#1b1c1c] active-press-sm"
                  >
                    保存并同步
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Save action bar */}
      <div className="bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        {saveSuccess ? (
          <div className="text-xs text-secondary font-bold flex items-center gap-1.5 animate-bounce">
            <Sparkles size={16} className="text-[#00731e]" />
            <span>吱！森林法则配对成功，设置档案已安全归巢！</span>
          </div>
        ) : saveError ? (
          <div className="text-xs font-bold text-red-600 flex items-center gap-1.5">
            <AlertTriangle size={16} className="text-red-500" />
            <span>{saveError}</span>
          </div>
        ) : (
          <div className="text-xs text-outline italic">
            松管家贴士：点击右侧“保存设置”，让松鼠打理树木更加安心自在！
          </div>
        )}

        <button
          onClick={handleSaveSettings}
          disabled={isSaving}
          className="bg-primary hover:bg-primary-container text-white border-2 border-on-background px-6 py-2.5 rounded-full font-display font-bold text-xs flex items-center justify-center gap-2 cursor-pointer shadow-[2px_3px_0_0_#1b1c1c] active-press ml-auto sm:ml-0 disabled:cursor-not-allowed disabled:opacity-60 disabled:translate-x-0 disabled:translate-y-0"
        >
          <Check size={16} /> {isSaving ? "正在保存..." : "保存所有设置"}
        </button>
      </div>

    </div>
  );
};
