import React, { useState } from "react";
import { InventoryItem, AppSettings } from "../types";
import SquirrelLogo from "./SquirrelLogo";
import { getItemStatus, CATEGORY_MAP } from "../utils";
import { motion } from "motion/react";
import {
  AlertTriangle, CheckCircle, Apple, AlertOctagon, Sparkles,
  ArrowRight, Search, ClipboardList, Lightbulb, ChefHat
} from "lucide-react";
import { Modal } from "./Modal";

interface DashboardProps {
  items: InventoryItem[];
  settings: AppSettings;
  onNavigateToTab: (tab: string) => void;
  onSetChatPreinput: (input: string) => void;
  onQuickCleanItem: (id: string) => Promise<void> | void;
  onViewItem: (item: InventoryItem) => void;
}

export const DashboardTab: React.FC<DashboardProps> = ({
  items,
  settings,
  onNavigateToTab,
  onSetChatPreinput,
  onQuickCleanItem,
  onViewItem,
}) => {
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    itemId: string;
    itemName: string;
  }>({ isOpen: false, itemId: "", itemName: "" });

  const [alertModal, setAlertModal] = useState<{
    isOpen: boolean;
    message: string;
  }>({ isOpen: false, message: "" });

  // Compute statuses
  const strategy = settings.expirationStrategy;
  
  const analyzedItems = items.map(item => ({
    ...item,
    analysis: getItemStatus(item, strategy)
  }));

  const expired = analyzedItems.filter(i => i.analysis.status === "expired");
  const warning = analyzedItems.filter(i => i.analysis.status === "warning");
  const fresh = analyzedItems.filter(i => i.analysis.status === "fresh");
  const permanent = analyzedItems.filter(i => i.analysis.status === "permanent");

  // Get food items about to expire
  const warningFood = warning.filter(i => i.category === "food");
  
  const handleAskRecipe = () => {
    let message = "推荐用我们树洞里现有的食材 ";
    if (warningFood.length > 0) {
      const names = warningFood.map(f => `【${f.name}】`).join("、");
      message += `${names}（临期了，急需吃掉吱）`;
    } else {
      const freshFood = fresh.filter(i => i.category === "food").slice(0, 2);
      if (freshFood.length > 0) {
        const names = freshFood.map(f => `【${f.name}】`).join("、");
        message += `加 ${names}`;
      } else {
        message += "松子和一些坚果";
      }
    }
    message += " 做个美味可口的松鼠创意料理，别忘照顾一下本松的习惯 " + settings.dietaryHabits.join("、") + " 哦！";
    onSetChatPreinput(message);
    onNavigateToTab("chat");
  };

  const handleAskInspect = (loc: string) => {
    onSetChatPreinput(`帮本松检查一下【${loc}】里现在存放了哪些藏品？它们都安稳妥当吗？吱！`);
    onNavigateToTab("chat");
  };

  return (
    <div className="space-y-7">
      {/* Banner / Mascot Greetings */}
      <div 
        id="mascot-greeting-banner"
        className="bg-white border-[3px] border-on-background shadow-[6px_8px_0_0_#1b1c1c] p-5 md:p-6 rounded-[34px] flex flex-col md:flex-row items-center gap-5 relative overflow-hidden"
      >
        <div className="absolute top-0 right-0 w-24 h-24 bg-primary opacity-5 rounded-full pointer-events-none" />
        <span className="shrink-0 animate-bounce rounded-full bg-primary text-white w-16 h-16 flex items-center justify-center border-2 border-on-background"><SquirrelLogo size={44} /></span>
        <div className="text-center md:text-left space-y-1.5 flex-1 select-none">
          <div className="bg-primary text-white text-[10px] font-bold px-3 py-1 rounded-full inline-block mb-1 border-2 border-on-background">
            {settings.squirrelPersonality === "humorous" && "🌰 金牌松鼠大管家"}
            {settings.squirrelPersonality === "gabby" && "🦜 博学话痨松"}
            {settings.squirrelPersonality === "gentle" && "🌸 温柔松姐姐"}
            {settings.squirrelPersonality === "strict_squirrel" && "🧹 整理魔王松"}
          </div>
          <h2 className="text-lg md:text-2xl font-display font-extrabold text-on-background">
            {settings.squirrelPersonality === "humorous" && "吱！‘果’真如此，今天也是充满干劲的收纳天！"}
            {settings.squirrelPersonality === "gabby" && "吱吱！本松听说你今天过得非常精彩，快帮我梳理梳理树洞的藏品！"}
            {settings.squirrelPersonality === "gentle" && "亲爱的小主人，累不累呀？快坐到本松铺满松针的软椅上歇歇吧。"}
            {settings.squirrelPersonality === "strict_squirrel" && "吱！你在发呆吗？赶紧打起精神！快来盘点树洞，乱糟糟可行不通！"}
          </h2>
          <p className="text-xs text-outline leading-tight font-sans">
            {expired.length > 0 
              ? `糟啦！发现树洞深处有 ${expired.length} 件藏品过保质期了！快去帮本松拔草，吱！` 
              : warning.length > 0 
                ? `主人！还有 ${warning.length} 件美味的粮食正处于临近变质的警戒边缘，不要浪费粮食吱！`
                : "秋收高捷！目前所有的树洞存粮和常备药均安全无虞，松鼠开心得原地转圈！"}
          </p>
        </div>

        {/* Quick action panel on banner */}
        <div className="flex gap-2 shrink-0 relative z-10">
          <button 
            onClick={() => onNavigateToTab("inventory")}
            className="flex items-center gap-1 bg-primary text-white font-display text-xs border-2 border-on-background px-5 py-2.5 rounded-full shadow-[2px_3px_0_0_#1b1c1c] hover:bg-primary-container active-press-sm cursor-pointer"
          >
            整理库存 <ArrowRight size={14} />
          </button>
        </div>
      </div>

      {/* Grid Counters Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Expired card */}
        <div className="bg-[#ffd5d1] border-[3px] border-red-500 shadow-[3px_4px_0_0_#1b1c1c] rounded-[28px] p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-[#8f1c17] font-bold">已过期 / 异常</div>
            <div className="text-3xl font-display font-extrabold text-error mt-1">{expired.length}</div>
            <span className="text-[10px] text-error font-bold">急需清理</span>
          </div>
          <div className="p-3 bg-[#ffe9e6] rounded-full border-2 border-on-background">
            <AlertOctagon className="text-red-600 stroke-[2.5]" size={22} />
          </div>
        </div>

        {/* Warning card */}
        <div className="bg-[#ffe92e] border-[3px] border-[#8f7a00] shadow-[3px_4px_0_0_#1b1c1c] rounded-[28px] p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-[#4f4500] font-bold">临期提醒中</div>
            <div className="text-3xl font-display font-extrabold text-[#665800] mt-1">{warning.length}</div>
            <span className="text-[10px] text-[#665800] font-bold">保质危急</span>
          </div>
          <div className="p-3 bg-[#fff27a] rounded-full border-2 border-on-background">
            <AlertTriangle className="text-[#665800] stroke-[2.5]" size={22} />
          </div>
        </div>

        {/* Fresh card */}
        <div className="bg-[#98f28d] border-[3px] border-[#18822a] shadow-[3px_4px_0_0_#1b1c1c] rounded-[28px] p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-[#0f5c1d] font-bold">新鲜安全</div>
            <div className="text-3xl font-display font-extrabold text-[#0f5c1d] mt-1">{fresh.length}</div>
            <span className="text-[10px] text-[#0f5c1d] font-bold">状态极佳</span>
          </div>
          <div className="p-3 bg-[#c7ffc2] rounded-full border-2 border-on-background">
            <CheckCircle className="text-[#0f7a24] stroke-[2.5]" size={22} />
          </div>
        </div>

        {/* Permanent items */}
        <div className="bg-[#ece7e8] border-[3px] border-[#7b6165] shadow-[3px_4px_0_0_#1b1c1c] rounded-[28px] p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-[#554045] font-bold">永固非消耗品</div>
            <div className="text-3xl font-display font-extrabold text-[#694f54] mt-1">{permanent.length}</div>
            <span className="text-[10px] text-[#694f54] font-bold">无保质期</span>
          </div>
          <div className="p-3 bg-white rounded-full border-2 border-on-background">
            <ClipboardList className="text-[#694f54] stroke-[2.5]" size={22} />
          </div>
        </div>
      </div>

      {/* Main split sections */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left column: Expiration list & clean ups */}
        <div className="col-span-1 lg:col-span-3 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-display font-extrabold text-on-background text-base flex items-center gap-1.5">
              <span>⚠️ 濒危食物/备急药品报警栈</span>
              <span className="text-xs font-mono font-normal bg-black text-white px-3 py-1 rounded-full">
                {expired.length + warning.length} 件
              </span>
            </h3>
          </div>

          <div className="space-y-3 overflow-y-auto max-h-[460px] pr-1 scrollbar-hide">
            {[...expired, ...warning].length === 0 ? (
              <div className="p-10 text-center bg-white border-[3px] border-dashed border-outline-variant rounded-[28px]">
                <span className="text-4xl block mb-2">🎈</span>
                <p className="text-sm font-semibold text-on-background">干干净净，粮仓满仓！</p>
                <p className="text-xs text-outline mt-1">目前没有任何过期或过保预警。太会过日子了，吱吱！</p>
              </div>
            ) : (
              [...expired, ...warning].map((item) => {
                const categoryColor = CATEGORY_MAP[item.category];
                const expState = getItemStatus(item, strategy);
                return (
                  <div
                    key={item.id}
                    className={`p-3 bg-white border-[3px] rounded-[24px] flex items-center gap-3 active-press transition-all hover:-translate-y-0.5 shadow-[2px_3px_0_0_#1b1c1c] ${
                      expState.status === "expired" ? "border-red-500" : "border-[#8f7a00]"
                    }`}
                  >
                    <div className="shrink-0 text-2xl bg-surface p-2 rounded-full border-2 border-on-background">
                      {item.category === "food" && "🍎"}
                      {item.category === "medicine" && "💊"}
                      {item.category === "electronics" && "🔌"}
                      {item.category === "cosmetics" && "🧴"}
                      {item.category === "book" && "📚"}
                      {item.category === "other" && "📦"}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span 
                          onClick={() => onViewItem(item)}
                          className="font-display font-bold text-[14px] text-on-background truncate hover:underline cursor-pointer"
                        >
                          {item.name}
                        </span>
                        <span className="text-[10px] bg-[#ffe92e] px-1.5 py-0.5 border border-on-background rounded font-mono">
                          {item.quantity}{item.unit}
                        </span>
                      </div>

                      <div className="flex items-center gap-2 mt-1 text-[11px] text-outline">
                        <span>{item.location}</span>
                        <span>•</span>
                        <span className={expState.status === "expired" ? "text-error font-semibold" : "text-[#665800] font-semibold"}>
                          {expState.displayText}
                        </span>
                      </div>
                    </div>

                    {/* Quick Clean Actions */}
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => onViewItem(item)}
                        className="px-2.5 py-1 text-[10px] border-2 border-on-background bg-[#ece7e8] rounded-full font-display text-on-background cursor-pointer hover:bg-white"
                      >
                        看档案
                      </button>
                      <button
                        onClick={() => {
                          setConfirmModal({
                            isOpen: true,
                            itemId: item.id,
                            itemName: item.name,
                          });
                        }}
                        className="px-2 py-1 bg-[#ffd5d1] hover:bg-[#ffe9e6] border-2 border-on-background text-[10px] text-error font-bold rounded-full cursor-pointer"
                        title="标记吃完/清理"
                      >
                        吃完/清掉
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right column: Dynamic cooking helpers & location inquiries */}
        <div className="col-span-1 lg:col-span-2 space-y-5">
          {/* Squirrel Recipes block */}
          <div className="bg-[#98f28d] border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-5 space-y-3 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-16 h-16 bg-secondary opacity-5 rounded-full" />
            <div className="flex items-center gap-2">
              <ChefHat className="text-white bg-[#1f1f1f] px-1 py-1 rounded-full border-2 border-on-background inline" size={32} />
              <div>
                <h4 className="font-display font-extrabold text-[15px] leading-tight text-on-background">今日食谱灵感配对</h4>
                <p className="text-[10px] text-[#18351d] font-semibold">巧用积压临期食品，践行零剩食生活</p>
              </div>
            </div>

            <div className="space-y-1.5 pt-1.5 text-xs text-on-background text-justify">
              <p className="leading-relaxed">
                {warningFood.length > 0 ? (
                  <>
                    吱吱！本松雷达识别到您手头有临期的食材：
                    <strong className="text-primary font-bold">
                      {warningFood.map(f => f.name).join("、")}
                    </strong>
                    。让金牌松鼠大管家立刻为您拟定一份完美解决胃口、规避过敏原的特制零浪费菜谱吧！
                  </>
                ) : (
                  <>
                    暂无临期食材警报，但别等快坏了再想呀！点下方按钮，本松随时结合你登记的
                    <strong className="text-secondary font-bold">
                       {settings.dietaryHabits.length > 0 ? settings.dietaryHabits.join("、") : "无刺激"} 
                    </strong>
                    饮食限制来给你推荐营养轻餐哦。
                  </>
                )}
              </p>
            </div>

            <button
              onClick={handleAskRecipe}
              className="w-full flex items-center justify-center gap-1 bg-[#1f1f1f] hover:bg-primary border-2 border-on-background text-white text-xs font-display font-bold py-2 px-4 rounded-full shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer"
            >
              <Sparkles size={13} className="text-white" /> 让松鼠写份创意菜单吱！
            </button>
          </div>

          {/* Quick interactive search prompts */}
          <div className="bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-5 space-y-3.5">
            <h4 className="font-display font-extrabold text-[14px] text-on-background flex items-center gap-1.5">
              <Lightbulb className="text-[#665800]" size={17} />
              <span>松鼠问答情报站</span>
            </h4>
            <p className="text-[11px] text-outline leading-tight">
              点击下方松鼠的日常工作流，快速呼叫AI管家为您定制收纳问答：
            </p>

            <div className="space-y-2">
              {settings.selectedLocations.slice(0, 3).map((loc) => (
                <button
                  key={loc}
                  onClick={() => handleAskInspect(loc)}
                  className="w-full text-left p-2.5 bg-surface hover:bg-[#ffe92e] border-2 border-on-background rounded-full text-xs flex items-center justify-between active-press"
                >
                  <span className="font-display font-medium text-on-background truncate">🔍 帮本松搜寻一下【{loc}】的存货</span>
                  <ArrowRight size={12} className="text-outline shrink-0 ml-1" />
                </button>
              ))}

              <button
                onClick={() => {
                  onSetChatPreinput("有何常备药可以常驻玄关柜？哪些已经快干涸啦？吱！");
                  onNavigateToTab("chat");
                }}
                className="w-full text-left p-2.5 bg-surface hover:bg-[#ffe92e] border-2 border-on-background rounded-full text-xs flex items-center justify-between active-press"
              >
                <span className="font-display font-medium text-on-background">💊 感冒常备药怎么在树梢归档？</span>
                <ArrowRight size={12} className="text-outline shrink-0 ml-1" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Modals */}
      <Modal
        isOpen={confirmModal.isOpen}
        onClose={() => setConfirmModal({ isOpen: false, itemId: "", itemName: "" })}
        onConfirm={() => {
          void Promise.resolve(onQuickCleanItem(confirmModal.itemId)).catch((error) => {
            console.error("Failed to quick clean item", error);
            setAlertModal({
              isOpen: true,
              message: "清理失败，请确认后端服务已启动后重试。",
            });
          });
        }}
        type="confirm"
        variant="warning"
        title="确认清理"
        message={`吱！您确定已经吃完或清理了【${confirmModal.itemName}】，并从清单中删除吗？`}
        confirmText="确认清理"
        cancelText="再想想"
      />

      <Modal
        isOpen={alertModal.isOpen}
        onClose={() => setAlertModal({ isOpen: false, message: "" })}
        type="alert"
        variant="danger"
        message={alertModal.message}
      />
    </div>
  );
};
