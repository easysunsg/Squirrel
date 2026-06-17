import React, { useMemo, useState } from "react";
import { AppSettings, SquirrelPersonality } from "../types";
import SquirrelLogo from "./SquirrelLogo";
import { motion, AnimatePresence } from "motion/react";
import {
  Home,
  CheckSquare,
  Square,
  ShieldAlert,
  Sparkles,
  ChevronRight,
  Heart,
  BellRing,
  UserCheck,
  Flame,
  Sprout,
} from "lucide-react";
import { ReminderSettingsPanel, LIFESTYLE_OPTIONS } from "./ReminderSettingsPanel";

interface OnboardingProps {
  settings: AppSettings;
  onSaveSettings: (settings: AppSettings) => Promise<void> | void;
}

const strategyReminderDays = {
  strict: 10,
  normal: 5,
  relaxed: 2,
};

const locationSpaceStyles = [
  { icon: "kitchen", bgClass: "bg-primary-fixed", textColor: "text-primary", badgeColor: "bg-secondary-container" },
  { icon: "shelves", bgClass: "bg-tertiary-fixed", textColor: "text-tertiary", badgeColor: "bg-surface-container-high" },
  { icon: "garage", bgClass: "bg-secondary-fixed", textColor: "text-secondary", badgeColor: "bg-surface-container-high" },
  { icon: "home_storage", bgClass: "bg-surface-container-high", textColor: "text-outline", badgeColor: "bg-surface-container" },
];

const defaultLocations = ["主冰箱", "厨房储物柜", "玄关柜"];

const availableLocations = [
  { name: "主冰箱", desc: "日常生鲜、水果、乳制品和剩菜保鲜", icon: "🥬" },
  { name: "厨房储物柜", desc: "油盐酱醋、干货调料和零食储藏", icon: "🥫" },
  { name: "玄关柜", desc: "常备药、钥匙、雨具和居家小件", icon: "🧴" },
  { name: "书房储物架", desc: "书籍资料、电子产品和办公杂物", icon: "📚" },
  { name: "卧室衣柜", desc: "换季衣物、被褥和香氛收纳", icon: "🧺" },
];

const presetHabits = [
  "海鲜过敏",
  "乳糖不耐受",
  "轻食主义",
  "拒绝浪费",
  "懒人速食",
  "零食控",
  "素食偏好",
  "重辣口味",
  "定期清理强迫症",
];

const lifestyleOptions = LIFESTYLE_OPTIONS;

export const Onboarding: React.FC<OnboardingProps> = ({ settings, onSaveSettings }) => {
  const [step, setStep] = useState(1);
  const [selectedLocs, setSelectedLocs] = useState<string[]>(
    settings.selectedLocations.length > 0 ? settings.selectedLocations : defaultLocations
  );
  const [selectedHabits, setSelectedHabits] = useState<string[]>(settings.dietaryHabits);
  const [lifestyleTag, setLifestyleTag] = useState<string>(
    settings.lifestyleTag || lifestyleOptions[0]
  );
  const [reminderTime, setReminderTime] = useState<string>(
    settings.reminderTime || "18:00"
  );
  const [strategy, setStrategy] = useState<"normal" | "strict" | "relaxed">(
    settings.expirationStrategy
  );
  const [personality, setPersonality] = useState<SquirrelPersonality>(
    settings.squirrelPersonality
  );
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const progressWidth = useMemo(() => `${(step / 4) * 100}%`, [step]);

  const handleToggleLoc = (name: string) => {
    if (selectedLocs.includes(name)) {
      if (selectedLocs.length > 1) {
        setSelectedLocs(selectedLocs.filter((loc) => loc !== name));
      }
      return;
    }
    setSelectedLocs([...selectedLocs, name]);
  };

  const handleToggleHabit = (name: string) => {
    if (selectedHabits.includes(name)) {
      setSelectedHabits(selectedHabits.filter((habit) => habit !== name));
      return;
    }
    setSelectedHabits([...selectedHabits, name]);
  };

  const handleNext = async () => {
    if (step < 4) {
      setStep(step + 1);
      setSaveError(null);
      return;
    }

    const nextSettings: AppSettings = {
      onboardingComplete: true,
      selectedLocations: selectedLocs,
      dietaryHabits: selectedHabits,
      lifestyleTag,
      reminderTime,
      expirationStrategy: strategy,
      squirrelPersonality: personality,
    };

    setIsSaving(true);
    setSaveError(null);

    try {
      await onSaveSettings(nextSettings);
    } catch (error) {
      console.error("Failed to save onboarding settings", error);
      setSaveError("设置保存失败，请确认后端服务已启动后重试。");
    } finally {
      setIsSaving(false);
    }
  };

  const handlePrev = () => {
    if (step > 1) {
      setStep(step - 1);
    }
  };

  return (
    <div className="min-h-screen bg-background bg-paper flex items-center justify-center p-4">
      <div
        id="onboarding-card"
        className="w-full max-w-2xl bg-white border-2 border-on-background hard-shadow p-6 md:p-8 rounded-3xl relative overflow-hidden"
      >
        <div className="absolute top-0 right-0 w-32 h-32 bg-primary-fixed rounded-bl-full -z-10 opacity-70" />
        <div className="absolute bottom-0 left-0 w-24 h-24 bg-secondary-fixed rounded-tr-full -z-10 opacity-50" />

        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <SquirrelLogo size={32} />
            <div>
              <h1 className="font-display font-medium text-lg leading-none text-on-background">
                松鼠筑巢
              </h1>
              <p className="text-xs text-outline font-sans">首次进入前的个性化设置</p>
            </div>
          </div>
          <div className="font-mono text-sm bg-surface-container px-3 py-1 border-2 border-on-background rounded-full">
            {step} / 4
          </div>
        </div>

        <div className="w-full h-3 border-2 border-on-background bg-surface-container rounded-full mb-8 relative overflow-hidden">
          <motion.div
            className="h-full bg-primary"
            initial={{ width: "25%" }}
            animate={{ width: progressWidth }}
            transition={{ duration: 0.3 }}
          />
        </div>

        <AnimatePresence mode="wait">
          {step === 1 && (
            <motion.div
              key="step-1"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-4"
            >
              <div className="space-y-1">
                <span className="text-xs font-bold text-primary uppercase tracking-wide flex items-center gap-1">
                  <Home size={14} className="stroke-[2.5]" /> 第一步：收纳空间
                </span>
                <h2 className="text-xl md:text-2xl font-display font-medium text-on-background">
                  先告诉松鼠，你想管理哪些生活空间
                </h2>
                <p className="text-sm text-outline">
                  这些空间会影响库存归类、提醒推荐和后续问答建议。
                </p>
              </div>

              <div className="space-y-2 pt-2">
                {availableLocations.map((loc) => {
                  const isSelected = selectedLocs.includes(loc.name);
                  return (
                    <button
                      key={loc.name}
                      onClick={() => handleToggleLoc(loc.name)}
                      className={`w-full flex items-center gap-4 p-4 border-2 border-on-background rounded-2xl text-left active-press transition-colors ${
                        isSelected ? "bg-primary-fixed" : "bg-surface hover:bg-surface-container-high"
                      }`}
                    >
                      <div className="text-3xl">{loc.icon}</div>
                      <div className="flex-1">
                        <div className="font-display font-medium text-on-background text-[15px]">
                          {loc.name}
                        </div>
                        <div className="text-xs text-outline mt-0.5">{loc.desc}</div>
                      </div>
                      <div>
                        {isSelected ? (
                          <CheckSquare className="text-primary stroke-[2.5]" size={22} />
                        ) : (
                          <Square className="text-outline stroke-[1.5]" size={22} />
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </motion.div>
          )}

          {step === 2 && (
            <motion.div
              key="step-2"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-5"
            >
              <div className="space-y-1">
                <span className="text-xs font-bold text-secondary uppercase tracking-wide flex items-center gap-1">
                  <Heart size={14} className="stroke-[2.5]" /> 第二步：饮食习惯
                </span>
                <h2 className="text-xl md:text-2xl font-display font-medium text-on-background">
                  记录你的偏好、忌口和生活习惯
                </h2>
                <p className="text-sm text-outline">
                  松鼠会在库存提醒和 AI 对话里尽量贴合这些习惯。
                </p>
              </div>

              <div className="flex flex-wrap gap-2.5 pt-2">
                {presetHabits.map((habit) => {
                  const isSelected = selectedHabits.includes(habit);
                  return (
                    <button
                      key={habit}
                      onClick={() => handleToggleHabit(habit)}
                      className={`px-4 py-2.5 text-sm border-2 border-on-background rounded-full active-press transition-all font-medium ${
                        isSelected
                          ? "bg-secondary text-white hard-shadow-sm translate-x-[-1px] translate-y-[-1px]"
                          : "bg-surface text-on-background hover:bg-surface-container-high"
                      }`}
                    >
                      {habit}
                    </button>
                  );
                })}
              </div>

              <div className="p-4 bg-secondary-container text-on-secondary-container border-2 border-on-background rounded-2xl text-xs flex gap-3">
                <ShieldAlert className="shrink-0 text-secondary mt-0.5" size={16} />
                <p className="leading-relaxed font-sans">
                  <strong>说明：</strong> 这些偏好保存在本地浏览器中，用来帮助提醒、推荐菜谱和整理建议更贴近你的日常。
                </p>
              </div>
            </motion.div>
          )}

          {step === 3 && (
            <motion.div
              key="step-3"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-5"
            >
              <div className="space-y-1">
                <span className="text-xs font-bold text-[#00731e] uppercase tracking-wide flex items-center gap-1">
                  <Sprout size={14} className="stroke-[2.5]" /> 第三步：生活标签与提醒时间
                </span>
                <h2 className="text-xl md:text-2xl font-display font-medium text-on-background">
                  设定你的生活标签和每日提醒时间
                </h2>
                <p className="text-sm text-outline">
                  参考你给的视觉稿，我把这部分做成两张独立卡片，首次进入就能直接完成设置。
                </p>
              </div>

              <ReminderSettingsPanel
                lifestyleTag={lifestyleTag}
                reminderTime={reminderTime}
                onLifestyleTagChange={setLifestyleTag}
                onReminderTimeChange={setReminderTime}
                variant="onboarding"
              />
            </motion.div>
          )}

          {step === 4 && (
            <motion.div
              key="step-4"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-6"
            >
              <div className="space-y-1">
                <span className="text-xs font-bold text-tertiary-container uppercase tracking-wide flex items-center gap-1">
                  <UserCheck size={14} className="stroke-[2.5]" /> 第四步：提醒策略与管家性格
                </span>
                <h2 className="text-xl md:text-2xl font-display font-medium text-on-background">
                  最后选一下提醒强度和松鼠管家的说话风格
                </h2>
                <p className="text-sm text-outline">
                  这些设置会直接影响首页提醒方式和聊天语气。
                </p>
              </div>

              <div className="space-y-2">
                <label className="text-[14px] font-bold text-on-background flex items-center gap-1.5">
                  <BellRing size={16} className="text-primary" /> 临期提醒策略
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { key: "strict", title: "严格模式", desc: "提前 10 天提醒" },
                    { key: "normal", title: "标准模式", desc: "提前 5 天提醒" },
                    { key: "relaxed", title: "轻松模式", desc: "提前 2 天提醒" },
                  ].map((item) => (
                    <button
                      key={item.key}
                      onClick={() => setStrategy(item.key as "normal" | "strict" | "relaxed")}
                      className={`p-3 border-2 border-on-background rounded-2xl text-center active-press-sm cursor-pointer transition-all ${
                        strategy === item.key
                          ? "bg-primary-fixed hard-shadow-sm -translate-y-0.5"
                          : "bg-surface text-on-background hover:bg-[#eae7e7]"
                      }`}
                    >
                      <div className="font-display font-medium text-xs md:text-sm text-on-background">
                        {item.title}
                      </div>
                      <div className="text-[10px] text-outline mt-0.5 leading-tight">{item.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-[14px] font-bold text-on-background flex items-center gap-1.5">
                  <Flame size={16} className="text-secondary" /> 松鼠管家性格
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { key: "humorous", emoji: "😄", title: "幽默松鼠", desc: "轻松一点，时不时开个玩笑" },
                    { key: "gabby", emoji: "🤓", title: "话痨松鼠", desc: "信息量更足，解释更积极" },
                    { key: "gentle", emoji: "🌷", title: "温柔松鼠", desc: "提醒更柔和，表达更贴心" },
                    { key: "strict_squirrel", emoji: "🧹", title: "严格松鼠", desc: "更强调整理和及时处理" },
                  ].map((item) => (
                    <button
                      key={item.key}
                      onClick={() => setPersonality(item.key as SquirrelPersonality)}
                      className={`p-3 border-2 border-on-background rounded-2xl text-left active-press-sm cursor-pointer transition-all ${
                        personality === item.key
                          ? "bg-[#91f78e] hard-shadow-sm -translate-y-0.5"
                          : "bg-surface text-on-background hover:bg-[#eae7e7]"
                      }`}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="text-base">{item.emoji}</span>
                        <span className="font-display font-medium text-xs md:text-sm text-on-background">
                          {item.title}
                        </span>
                      </div>
                      <div className="text-[10px] text-outline mt-1 leading-tight">{item.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex items-center justify-between mt-8 pt-4 border-t border-surface-container">
          {step > 1 ? (
            <button
              onClick={handlePrev}
              className="px-5 py-2.5 text-sm font-display font-medium border-2 border-on-background rounded-xl active-press hover:bg-surface-container-high bg-white text-on-background cursor-pointer"
            >
              上一步
            </button>
          ) : (
            <div />
          )}

          <button
            onClick={handleNext}
            disabled={isSaving}
            className="flex items-center gap-1 px-6 py-2.5 text-sm font-display font-medium border-2 border-on-background bg-primary text-white hover:bg-opacity-95 rounded-xl hard-shadow-sm active-press cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 disabled:translate-x-0 disabled:translate-y-0"
          >
            {isSaving ? "正在保存..." : step === 4 ? "完成设置，进入松鼠筑巢" : "下一步"}
            <ChevronRight size={16} />
          </button>
        </div>

        {saveError && (
          <div className="mt-4 rounded-2xl border-2 border-red-500 bg-red-50 px-4 py-3 text-xs font-medium text-red-700">
            {saveError}
          </div>
        )}

        {step === 4 && (
          <div className="mt-4 rounded-2xl border-2 border-on-background bg-surface-container px-4 py-3 text-xs text-outline flex items-center gap-2">
            <Sparkles size={14} className="text-primary shrink-0" />
            当前将保存为：{lifestyleTag}，每日 {reminderTime} 提醒。
          </div>
        )}
      </div>
    </div>
  );
};
