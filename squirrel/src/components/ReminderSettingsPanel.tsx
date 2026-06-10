import React from "react";
import { Bell, CheckCircle2, Circle, Clock3, Sprout } from "lucide-react";

interface ReminderSettingsPanelProps {
  lifestyleTag: string;
  reminderTime: string;
  onLifestyleTagChange: (value: string) => void;
  onReminderTimeChange: (value: string) => void;
  variant?: "onboarding" | "modal";
}

export const LIFESTYLE_OPTIONS = ["减脂增肌中", "佛系干饭人", "精致生活家"];
export const REMINDER_PRESETS = ["07:30", "12:00", "18:00", "21:00"];

export const ReminderSettingsPanel: React.FC<ReminderSettingsPanelProps> = ({
  lifestyleTag,
  reminderTime,
  onLifestyleTagChange,
  onReminderTimeChange,
  variant = "onboarding",
}) => {
  const sectionShadowClass =
    variant === "modal"
      ? "shadow-[4px_5px_0_0_#1b1c1c]"
      : "shadow-[6px_8px_0_0_#1b1c1c]";
  const headingClass = variant === "modal" ? "text-xl" : "text-2xl";
  const timeTextClass = variant === "modal" ? "text-2xl" : "text-2xl md:text-3xl";

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <section className={`bg-white border-2 border-on-background rounded-[28px] p-5 space-y-4 ${sectionShadowClass}`}>
        <div className="flex items-center gap-2">
          <Sprout className="text-secondary" size={20} />
          <h3 className={`font-display font-bold text-on-background ${headingClass}`}>生活标签</h3>
        </div>

        <div className="space-y-3">
          {LIFESTYLE_OPTIONS.map((option) => {
            const isSelected = lifestyleTag === option;
            return (
              <button
                key={option}
                onClick={() => onLifestyleTagChange(option)}
                className={`w-full flex items-center gap-3 rounded-full border-2 border-on-background px-4 py-3 text-left transition-all active-press ${
                  isSelected ? "bg-surface-container hard-shadow-sm -translate-y-0.5" : "bg-white"
                }`}
              >
                {isSelected ? (
                  <CheckCircle2 size={18} className="text-secondary shrink-0" />
                ) : (
                  <Circle size={18} className="text-secondary shrink-0" />
                )}
                <span className="font-medium text-on-background">{option}</span>
              </button>
            );
          })}
        </div>
      </section>

      <section className={`bg-white border-2 border-on-background rounded-[28px] p-5 space-y-4 ${sectionShadowClass}`}>
        <div className="flex items-center gap-2">
          <Bell className="text-tertiary" size={20} />
          <h3 className={`font-display font-bold text-on-background ${headingClass}`}>提醒时间</h3>
        </div>

        <div className="rounded-[28px] border-2 border-on-background bg-[#ffe92e] px-5 py-6 text-center shadow-[2px_3px_0_0_#1b1c1c]">
          <p className="text-xs font-bold text-[#665800]">每日固定提醒</p>
          <p className={`mt-2 font-display font-extrabold text-on-background ${timeTextClass}`}>每天 {reminderTime}</p>
          <p className="mt-2 text-xs text-[#665800]">松鼠管家会按这个时间帮你检查临期库存</p>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {REMINDER_PRESETS.map((time) => {
            const isSelected = reminderTime === time;
            return (
              <button
                key={time}
                onClick={() => onReminderTimeChange(time)}
                className={`rounded-full border-2 border-on-background px-3 py-2 text-sm font-medium active-press-sm ${
                  isSelected ? "bg-tertiary-fixed text-on-background hard-shadow-sm" : "bg-white"
                }`}
              >
                {time}
              </button>
            );
          })}
        </div>

        <label className="block space-y-2">
          <span className="text-xs font-bold text-outline flex items-center gap-1">
            <Clock3 size={14} /> 修改提醒时间
          </span>
          <input
            type="time"
            value={reminderTime}
            onChange={(e) => onReminderTimeChange(e.target.value)}
            className="w-full rounded-full border-2 border-on-background bg-white px-4 py-3 text-sm font-medium outline-none focus:bg-surface"
          />
        </label>
      </section>
    </div>
  );
};
