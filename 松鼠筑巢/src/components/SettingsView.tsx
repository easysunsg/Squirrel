import React, { useState } from 'react';
import { SystemPreferences } from '../types';
import { Settings, Sliders, RefreshCw, AlertTriangle, ShieldCheck, Database, Volume2, Save, Trash2, CheckCircle } from 'lucide-react';

interface SettingsViewProps {
  preferences: SystemPreferences;
  onSavePreferences: (updated: SystemPreferences) => void;
  onResetAllData: () => void;
}

export default function SettingsView({
  preferences,
  onSavePreferences,
  onResetAllData
}: SettingsViewProps) {
  // Temporary component states mirroring the parent model
  const [aiModel, setAiModel] = useState(preferences.aiModel || 'gemini-3.5-flash');
  const [temperature, setTemperature] = useState(preferences.temperature || 0.7);
  const [autoTag, setAutoTag] = useState(preferences.autoTag ?? true);
  const [savingPath, setSavingPath] = useState(preferences.savingPath || '~/Documents/SongShuZhuChao/Library');
  const [warningThreshold, setWarningThreshold] = useState(preferences.warningThreshold || 5);
  const [lowThreshold, setLowThreshold] = useState(preferences.lowThreshold || 15);
  const [reminderTime, setReminderTime] = useState(preferences.reminderTime || '18:00');

  const [isSyncing, setIsSyncing] = useState(false);
  const [syncTime, setSyncTime] = useState('刚刚');

  const handleSyncManual = () => {
    setIsSyncing(true);
    setTimeout(() => {
      setIsSyncing(false);
      setSyncTime(new Date().toLocaleTimeString());
      alert("🎉 筑巢本地Markdown物理备忘文件已与iCloud/本地库完全离线强同步成功！");
    }, 1500);
  };

  const handleSave = () => {
    onSavePreferences({
      allergies: preferences.allergies,
      lifestyle: preferences.lifestyle,
      warningThreshold,
      lowThreshold,
      reminderTime,
      savingPath,
      aiModel,
      temperature,
      autoTag
    });
    alert("💾 设置已成功保存至松鼠小脑，系统阈值自动调整到位！");
  };

  const handleResetToDefault = () => {
    if (confirm("⚠️ 注意！这将清除当前所有自定义库存档案和对话记忆，并恢复到系统模版数据状态，您确定要继续吗？🐿️")) {
      onResetAllData();
      alert("✅ 已成功重置！页面将更新加载松鼠管家初始生态。");
    }
  };

  return (
    <div className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-12 gap-8 mt-8 pb-12 select-none">
      
      {/* Left Column: Specific entry controls (8 columns) */}
      <div className="md:col-span-8 bg-white border-2 border-on-surface p-6 md:p-8 rounded-2xl shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] space-y-8">
        
        {/* Title Header */}
        <div className="flex items-center gap-3 border-b-2 border-on-surface pb-4">
          <span className="bg-primary text-white p-2 rounded-full border border-on-surface">
            <Settings className="w-5 h-5" />
          </span>
          <div>
            <h2 className="text-xl md:text-2xl font-headline-lg font-black text-on-surface">系统参数设定</h2>
            <p className="text-xs text-on-surface-variant font-bold">微调松鼠筑巢的各项预警以及AI智能引擎机制。</p>
          </div>
        </div>

        {/* SECTION 1: AI Configurations */}
        <div className="space-y-4">
          <h3 className="font-extrabold text-sm text-primary flex items-center gap-1.5 border-b border-dashed border-on-surface pb-1.5">
            <Sliders className="w-4 h-4" /> 🤖 AI 智能引擎及解析设定
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-bold font-sans">
            <div>
              <label className="block text-on-surface-variant mb-1 ml-0.5">主分类判定模型 (Large Language Model)</label>
              <select
                value={aiModel}
                onChange={(e) => setAiModel(e.target.value)}
                className="w-full border-2 border-on-surface p-2.5 rounded-lg bg-white font-black"
              >
                <option value="gemini-3.5-flash">Gemini 3.5 Flash (推荐轻便)</option>
                <option value="gemini-3.1-pro-preview">Gemini 3.1 Pro (深度推理)</option>
                <option value="gpt-4o-nest">GPT-4o 筑巢专用版</option>
                <option value="claude-3.5">Claude 3.5 Sonnet</option>
              </select>
            </div>

            <div>
              <label className="block text-on-surface-variant mb-1 ml-0.5">对话创造力 (Model Temperature: {temperature})</label>
              <div className="flex gap-3 items-center pt-2">
                <input 
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.1"
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                  className="w-full h-2 bg-surface-container-high rounded-full cursor-pointer accent-primary border border-on-surface"
                />
                <span className="bg-surface-container-high border border-on-surface px-2.5 py-1 rounded font-mono font-black">{temperature}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 pt-1">
            <input 
              type="checkbox" 
              id="autotagging"
              checked={autoTag}
              onChange={(e) => setAutoTag(e.target.checked)}
              className="w-4 h-4 text-primary border-2 border-on-surface rounded focus:ring-0 checked:bg-primary"
            />
            <label htmlFor="autotagging" className="text-xs font-bold text-on-surface select-none cursor-pointer">
              开启 AI 闪电录入自动标签分类 (根据剩余量自动转换标记为 告急/较低/充足)
            </label>
          </div>
        </div>

        {/* SECTION 2: Storage Data Paths & Offline Sync */}
        <div className="space-y-4">
          <h3 className="font-extrabold text-sm text-secondary flex items-center gap-1.5 border-b border-dashed border-on-surface pb-1.5">
            <Database className="w-4 h-4" /> 📂 离线本底 Markdown 存储与同步
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-bold">
            <div>
              <label className="block text-on-surface-variant mb-1 ml-0.5">本地巢档案物理路径 (Markdown Database Location)</label>
              <input 
                type="text" 
                value={savingPath}
                onChange={(e) => setSavingPath(e.target.value)}
                placeholder="~/Documents/SongShuZhuChao/Library"
                className="w-full border-2 border-on-surface p-2.5 rounded-lg focus:outline-none focus:ring-0 font-medium"
              />
            </div>

            <div>
              <label className="block text-on-surface-variant mb-1.5 ml-0.5">备份与云端同步状态 (Offline Synchronizer)</label>
              <div className="flex items-center gap-3 bg-secondary-fixed p-2 border-2 border-on-surface rounded-lg justify-between">
                <span className="flex items-center gap-1 text-[11px] font-black text-on-secondary-fixed">
                  <span className="relative flex h-2 w-2 mr-0.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                  </span>
                  离线备份已同步 (上次: {syncTime})
                </span>
                
                <button
                  onClick={handleSyncManual}
                  disabled={isSyncing}
                  className="bg-white border border-on-surface py-1.5 px-3 rounded text-[10px] shadow-[1.5px_1.5px_0px_0px_#000] cursor-pointer hover:bg-surface-container-high transition-colors flex items-center gap-1"
                >
                  <RefreshCw className={`w-3 h-3 ${isSyncing ? 'animate-spin' : ''}`} /> 立即同步
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* SECTION 3: Threshold customizations */}
        <div className="space-y-4">
          <h3 className="font-extrabold text-sm text-tertiary flex items-center gap-1.5 border-b border-dashed border-on-surface pb-1.5">
            <ShieldCheck className="w-4 h-4" /> 📐 自定义预警/临期红黄线划分门槛
          </h3>

          <div className="grid grid-cols-3 gap-4 text-xs font-bold leading-relaxed">
            <div className="bg-[#fff5f5] p-3 rounded-xl border border-error">
              <label className="block text-error text-[10px] mb-1 font-black">🔴 库存告罄 (Warning Threshold)</label>
              <div className="flex items-center gap-1">
                <input 
                  type="number" 
                  value={warningThreshold} 
                  onChange={(e) => setWarningThreshold(Number(e.target.value))}
                  className="bg-white border-2 border-on-surface p-1.5 rounded text-center w-20 font-black"
                />
                <span className="text-on-surface-variant text-[10px]">% 标红线</span>
              </div>
            </div>

            <div className="bg-[#fffdf0] p-3 rounded-xl border border-tertiary">
              <label className="block text-tertiary text-[10px] mb-1 font-black">🟡 补货提示线 (Low Threshold)</label>
              <div className="flex items-center gap-1">
                <input 
                  type="number" 
                  value={lowThreshold} 
                  onChange={(e) => setLowThreshold(Number(e.target.value))}
                  className="bg-white border-2 border-on-surface p-1.5 rounded text-center w-20 font-black"
                />
                <span className="text-on-surface-variant text-[10px]">% 提醒</span>
              </div>
            </div>

            <div className="bg-[#f0fbf0] p-3 rounded-xl border border-secondary text-on-surface">
              <label className="block text-secondary text-[10px] mb-1 font-black">🟢 安全高枕线 (Full Scale)</label>
              <div className="flex items-center gap-1 h-9">
                <input 
                  type="text" 
                  value="15 件以上" 
                  disabled
                  className="bg-secondary-fixed-dim/40 border border-on-surface/20 p-1.5 rounded text-center w-22 font-extrabold text-[#777] cursor-not-allowed"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Global Action items */}
        <div className="flex justify-end gap-3 pt-6 border-t-2 border-on-surface">
          <button 
            onClick={handleSave}
            className="bg-primary text-white px-8 py-3 rounded-full font-headline-lg font-black text-sm border-2 border-on-surface shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] hover:translate-y-px hover:translate-x-px hover:shadow-[3px_3px_0px_0px_#1b1c1c] active:translate-y-0.5 active:shadow-none duration-75 cursor-pointer flex items-center gap-1.5"
          >
            <Save className="w-4 h-4" /> 保存生效
          </button>
        </div>

      </div>

      {/* Right Column: Organization is Art decal card (4 columns) */}
      <div className="md:col-span-4 space-y-8 select-none">
        
        {/* Playful Art Card sticker */}
        <section className="bg-white border-2 border-on-surface p-4 rounded-xl shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] rotate-[-1deg] text-center">
          <img 
            alt="Organization sticker print" 
            className="w-full h-48 object-cover rounded-lg border-2 border-on-surface mb-3" 
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuA7jFDfaSgLWA7gBFGF1q9TZtR4sY2tT7oUJfFj55pTadw65StR5zSdxTLvuoOgeN-bznb_Ps5GAPTe-N5-DhSuN4dRlXnqVFUiTEigIziMUbJ_7XhxI9tjC83dO7t9hRceA2wVaiRMclOCsyYRr5kzIcadKTCIKeZVx_z-FZsrjb9iMDJSIjJyCL7SV8YQ7dqULM-KKWrcYlEzL1dcsqBAj4m_SfE9uiD-NVBDiIA_sGw0qQvuopV__oPgs1Kdis_oUGaUqxumQ1M-"
            referrerPolicy="no-referrer"
          />
          <h4 className="font-extrabold text-sm text-on-surface">“组织即艺术”</h4>
          <span className="text-[10px] text-on-surface-variant font-mono font-bold block mt-1">—— 松鼠筑巢美学守则一期</span>
        </section>

        {/* Restore card block */}
        <section className="bg-error-container/20 border-2 border-on-surface p-5 rounded-xl shadow-[3px_3px_0px_0px_#1b1c1c] text-center space-y-4">
          <h5 className="font-black text-xs text-error flex items-center gap-1 justify-center">
            <AlertTriangle className="w-4 h-4" /> 危险或诊断区域
          </h5>
          <p className="text-[10px] text-on-surface-variant font-bold leading-relaxed">
            重置动作将擦去所有记录（牛奶，工具，面包以及管家对话树历史等），恢复出厂松鼠预留模板。
          </p>
          <button
            onClick={handleResetToDefault}
            className="w-full py-2.5 bg-error-container hover:bg-error hover:text-white text-error border-2 border-on-surface font-black text-xs rounded-xl shadow-[2px_2px_0px_0px_#1b1c1c] active:translate-y-px duration-75 transition-all cursor-pointer"
          >
            恢复原始默认设置
          </button>
        </section>
      </div>

    </div>
  );
}
