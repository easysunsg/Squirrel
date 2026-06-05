import React, { useState, useEffect } from 'react';
import { Space, Item, SystemPreferences } from '../types';
import { Bolt, Refrigerator, Clipboard, Settings, HelpCircle, Inbox, Plus, ChevronRight, HelpCircle as TipIcon, Calendar, RotateCcw, AlertCircle, ShoppingBag, Sparkles, CookingPot } from 'lucide-react';

interface DashboardViewProps {
  items: Item[];
  spaces: Space[];
  preferences: SystemPreferences;
  onNavigateToTab: (tab: string) => void;
  onAddItem: (item: Partial<Item>) => void;
  onConsumeItem: (id: string, ratio: number) => void;
  onDiscardItem: (id: string) => void;
}

export default function DashboardView({
  items,
  spaces,
  preferences,
  onNavigateToTab,
  onAddItem,
  onConsumeItem,
  onDiscardItem
}: DashboardViewProps) {
  const [lightningText, setLightningText] = useState('');
  const [isParsing, setIsParsing] = useState(false);
  const [parsedFeedback, setParsedFeedback] = useState<string | null>(null);

  // Dynamic Recipe advisor state
  const [recipe, setRecipe] = useState<any>({
    title: "番茄牛腩",
    description: "根据你的冰箱存货，我们发现番茄还剩2个，牛肉需要尽快吃掉。再配上仓库里的洋葱，完美！",
    ingredients: "番茄 2个, 牛腩 300g, 洋葱 1个",
    steps: [
      "牛腩洗净切块，冷水焯水捞出",
      "番茄切块，部分炒起沙，放入牛腩与汤料小火慢炖一小时",
      "出炉前加入剩下番茄，收汁即可食用！"
    ]
  });
  const [isRecipeLoading, setIsRecipeLoading] = useState(false);
  const [showRecipeModal, setShowRecipeModal] = useState(false);

  // Dynamic status counters calculated directly from alive state!
  const urgentCount = items.filter(i => i.tag === '告急' || i.tag === '过期预警').length;
  const lowCount = items.filter(i => i.tag === '较低').length;
  const healthyCount = items.filter(i => i.tag === '充足').length;

  const urgentListStr = items.filter(i => i.tag === '告急' || i.tag === '过期预警').map(i => i.title).slice(0, 3).join('、') || '无';
  const lowListStr = items.filter(i => i.tag === '较低').map(i => i.title).slice(0, 2).join('、') || '无';

  // Lightning entry integration
  const handleLightningSubmit = async () => {
    if (!lightningText.trim()) return;
    setIsParsing(true);
    setParsedFeedback(null);

    try {
      const res = await fetch("/api/lightning", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: lightningText })
      });
      const data = await res.json();
      if (data.items && data.items.length > 0) {
        const itemToInjest = data.items[0];
        // Add to state
        onAddItem({
          title: itemToInjest.title,
          spaceId: itemToInjest.spaceName === '车库工具' ? 'garage' : (itemToInjest.spaceName === '储藏间' ? 'storage' : 'kitchen'),
          spaceName: itemToInjest.spaceName,
          location: itemToInjest.location,
          remainingPct: itemToInjest.remainingPct,
          count: itemToInjest.count,
          unit: itemToInjest.unit,
          tag: itemToInjest.remainingPct < 20 ? '告急' : (itemToInjest.remainingPct < 50 ? '较低' : '充足'),
          icon: itemToInjest.icon || 'package_2'
        });

        setParsedFeedback(`🎉 AI成功录入【${itemToInjest.title}】到【${itemToInjest.spaceName}】！`);
        setLightningText('');
      } else {
        setParsedFeedback("小松鼠没能识别出具体物品，换种描述试试吧～");
      }
    } catch (e) {
      console.error(e);
      setParsedFeedback("整理网络打盹了，小松鼠帮您自动记录进主厨房啦！");
      onAddItem({
        title: lightningText.slice(0, 8),
        spaceId: 'kitchen',
        spaceName: '主厨房',
        location: '厨房架子',
        remainingPct: 90,
        count: 1,
        unit: '个',
        tag: '充足',
        icon: 'package_2'
      });
      setLightningText('');
    } finally {
      setIsParsing(false);
      setTimeout(() => setParsedFeedback(null), 4000);
    }
  };

  // Recipe planner dynamic cycler
  const handleSwapRecipe = async () => {
    setIsRecipeLoading(true);
    try {
      const res = await fetch("/api/recipe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          inventory: items,
          excludedRecipeTitle: recipe.title,
          systemPreferences: preferences
        })
      });
      const data = await res.json();
      if (data.recipe) {
        setRecipe(data.recipe);
      }
    } catch {
      // Fallback toggling
      const current = recipe.title;
      if (current === "番茄牛腩") {
        setRecipe({
          title: "香烤坚果面包片",
          description: "发现你的常备全麦面包已经临期了（告急！剩15%），坚果也剩一小把，用来烤酥香面包片非常搭配！",
          ingredients: "全麦面包 2片, 混合坚果 一小把, 蜂蜜适量",
          steps: ["将全麦面包平铺于烤架上", "坚果碾碎均匀洒于面包表面", "烤箱180度慢烤5分钟，出炉淋少许蜂蜜！"]
        });
      } else {
        setRecipe({
          title: "番茄牛腩",
          description: "根据你的冰箱存货，我们发现番茄还剩2个，牛肉需要尽快吃掉。再配上仓库里的洋葱，完美！",
          ingredients: "番茄 2个, 牛腩 300g, 洋葱 1个",
          steps: ["牛腩切块冷水下锅焯水备用", "番茄去皮炒出汁起沙，加入焖煮一小时", "起锅前加入洋葱、余下的番茄块提鲜！"]
        });
      }
    } finally {
      setIsRecipeLoading(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-12 gap-8 mt-8 pb-10">
      
      {/* Left Column: Focus & Alerts (7 cols) */}
      <div className="md:col-span-7 space-y-8">
        
        {/* AI Input Block (Lightning Capsule) */}
        <section className="bg-white border-2 border-primary p-6 rounded-xl shadow-[6px_6px_0px_0px_rgba(183,0,82,1)] rotate-[-0.5deg]">
          <div className="flex items-center gap-3 mb-4">
            <span className="bg-primary text-white p-2 rounded-full flex items-center justify-center border-2 border-on-surface">
              <Bolt className="w-5 h-5 fill-current" />
            </span>
            <h2 className="text-xl md:text-2xl font-headline-lg font-black text-on-surface">闪电录入</h2>
          </div>
          
          <div className="relative">
            <textarea 
              rows={3}
              value={lightningText}
              onChange={(e) => setLightningText(e.target.value)}
              className="w-full border-2 border-on-surface p-4 pr-24 rounded-lg font-sans focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary min-h-[100px] resize-none text-sm placeholder:text-on-surface-variant/50" 
              placeholder="输入你想存入的东西，或者刚才吃掉的东西... (例如：买了两盒牛奶放进主厨冰箱，或者 吃掉了半块面包 等)"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleLightningSubmit();
                }
              }}
            />
            <button 
              onClick={handleLightningSubmit}
              disabled={isParsing || !lightningText.trim()}
              className="absolute bottom-4 right-4 bg-primary text-white px-6 py-2 rounded-full font-bold shadow-[2px_2px_0px_0px_rgba(27,28,28,1)] hover:translate-y-px hover:translate-x-px hover:shadow-[1px_1px_0px_0px_#1b1c1c] active:translate-y-0.5 active:translate-x-0.5 active:shadow-none duration-75 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer text-sm"
            >
              {isParsing ? '录入中...' : '搞定！'}
            </button>
          </div>

          {parsedFeedback && (
            <div className="mt-3 p-2 bg-secondary-container text-on-secondary-container border-2 border-on-surface rounded-lg text-xs font-bold animate-pulse text-center">
              {parsedFeedback}
            </div>
          )}
        </section>

        {/* Status Dashboard Blocks (Three cards aligned slightly wonky) */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="border-2 border-on-surface p-4 rounded-xl shadow-[4px_4px_0px_0px_#1b1c1c] bg-error text-white rotate-1">
            <div className="text-white font-headline-lg text-4xl font-black mb-1">
              {String(urgentCount).padStart(2, '0')}
            </div>
            <div className="text-white text-xs font-bold uppercase tracking-wider">库存告罄</div>
            <p className="text-white/90 text-xs mt-2 line-clamp-2">快去补货：{urgentListStr}</p>
          </div>

          <div className="border-2 border-on-surface p-4 rounded-xl shadow-[4px_4px_0px_0px_#1b1c1c] bg-tertiary-fixed rotate-[-1deg]">
            <div className="text-on-tertiary-fixed font-headline-lg text-4xl font-black mb-1">
              {String(lowCount).padStart(2, '0')}
            </div>
            <div className="text-on-tertiary-fixed text-xs font-bold uppercase tracking-wider">低库存预警</div>
            <p className="text-on-tertiary-fixed-variant text-xs mt-2 line-clamp-2">这些不多啦：{lowListStr}</p>
          </div>

          <div className="border-2 border-on-surface p-4 rounded-xl shadow-[4px_4px_0px_0px_#1b1c1c] bg-secondary-container rotate-0.5">
            <div className="text-on-secondary-container font-headline-lg text-4xl font-black mb-1">
              {String(healthyCount).padStart(2, '0')}
            </div>
            <div className="text-on-secondary-container text-xs font-bold uppercase tracking-wider">库存充足</div>
            <p className="text-on-secondary-container text-xs mt-2 line-clamp-2">大部分囤货状态很健康哦！</p>
          </div>
        </div>

        {/* AI Today Recipe Recommendation block */}
        <section className="bg-secondary-fixed border-2 border-on-surface p-6 rounded-2xl shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] relative overflow-hidden" id="daily_recipe_box">
          <div className="relative z-10">
            <div className="bg-on-secondary-fixed text-white inline-block px-3 py-1 rounded-full text-xs font-bold mb-3 shadow-[1px_1px_0px_0px_#1b1c1c]">
              AI 厨房每日推荐
            </div>
            
            <h3 className="text-2xl font-headline-lg font-black text-on-secondary-fixed mb-2 flex items-center gap-1.5">
              <span>松鼠今日食谱：{recipe.title}</span>
            </h3>
            
            <p className="text-on-secondary-fixed-variant text-sm md:text-base font-semibold leading-relaxed mb-6 max-w-lg">
              {recipe.description}
            </p>

            <div className="flex gap-4">
              <button 
                onClick={() => setShowRecipeModal(true)}
                className="bg-on-surface text-white px-6 py-2.5 rounded-full font-bold hover:bg-primary transition-all shadow-[2px_2px_0px_0px_rgba(183,0,82,1)] duration-75 cursor-pointer text-sm flex items-center gap-1"
              >
                <CookingPot className="w-4 h-4" /> 开始烹饪
              </button>
              <button 
                onClick={handleSwapRecipe}
                disabled={isRecipeLoading}
                className="bg-white border-2 border-on-surface px-6 py-2.5 rounded-full font-bold shadow-[2px_2px_0px_0px_rgba(27,28,28,1)] hover:bg-surface-container active:translate-y-px duration-75 text-on-surface cursor-pointer text-sm"
              >
                {isRecipeLoading ? '小松鼠挑选中...' : '换一个'}
              </button>
            </div>
          </div>

          {/* Decorative squirrel background placeholder watermark icon */}
          <div className="absolute -bottom-6 -right-6 opacity-2 dark:opacity-10 text-on-secondary-fixed pointer-events-none select-none">
            <Sparkles className="w-40 h-40 animate-spin" style={{ animationDuration: '30s' }} />
          </div>
        </section>
      </div>

      {/* Right Column: Shortcuts & Space Lists (5 cols) */}
      <div className="md:col-span-5 space-y-8">
        
        {/* Quick Spaces List */}
        <section className="bg-white border-2 border-on-surface p-6 rounded-2xl shadow-[4px_4px_0px_0px_rgba(27,28,28,1)]">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl md:text-2xl font-headline-lg font-black">松鼠洞空间</h2>
            <button 
              onClick={() => onNavigateToTab('库存管理')}
              className="p-1 hover:bg-surface-container-high rounded-full transition-colors cursor-pointer text-primary"
            >
              <Plus className="w-6 h-6 stroke-[3]" />
            </button>
          </div>

          <div className="space-y-4">
            {spaces.map((space) => {
              // Get sample items for this space
              const spaceItems = items.filter(i => i.spaceId === space.id);
              const urgencyWarnCount = spaceItems.filter(i => i.tag === '告急' || i.tag === '过期预警').length;
              
              // Custom details text
              let desc = `${spaceItems.length} 件物品`;
              if (urgencyWarnCount > 0) {
                desc += ` · ${urgencyWarnCount}件告急预警`;
              } else if (space.id === 'storage') {
                desc += ` · 整理进度 80%`;
              } else if (space.id === 'garage') {
                desc += ` · 1件借出`;
              }

              return (
                <div 
                  key={space.id} 
                  className="border-b-2 border-on-surface pb-4 last:border-0 hover:bg-surface-container-lowest/50 p-2 rounded-xl transition-all"
                >
                  <div className="flex justify-between items-center">
                    <div className="flex items-center gap-3">
                      <div className={`w-12 h-12 rounded-lg border-2 border-on-surface ${space.bgClass} flex items-center justify-center text-on-surface shadow-[2px_2px_0px_0px_#1b1c1c]`}>
                        <span className="text-2xl font-bold">
                          {space.icon === 'kitchen' ? '🥛' : space.icon === 'shelves' ? '📦' : '🔧'}
                        </span>
                      </div>
                      <div>
                        <div className="text-base font-bold text-on-surface">{space.name}</div>
                        <div className="text-xs text-on-surface-variant font-medium">{desc}</div>
                      </div>
                    </div>

                    <div className="flex gap-2">
                      {space.id === 'kitchen' ? (
                        <>
                          <button 
                            onClick={() => {
                              const food = spaceItems.find(i => i.tag === '告急' || i.tag === '充足');
                              if (food) {
                                onConsumeItem(food.id, 50);
                                alert(`美味享用！已消耗 ${food.title} 的 50% 剩余量！🥞`);
                              } else {
                                alert("厨房暂时没有可以快速食用的推荐临期食材哦。");
                              }
                            }}
                            className="bg-secondary-container p-2 rounded-full border-2 border-on-surface shadow-[1px_1px_0px_0px_#1b1c1c] active:translate-y-0.5 duration-75 transition-transform cursor-pointer" 
                            title="一键标记本空间物品已食用"
                          >
                            🍽️
                          </button>
                          <button 
                            onClick={() => {
                              const food = spaceItems.find(i => i.tag === '过期预警' || i.tag === '告急');
                              if (food) {
                                onDiscardItem(food.id);
                                alert(`已清理过期物: ${food.title} 🧹`);
                              } else {
                                alert("没有需要清理的临期严重警告物品。");
                              }
                            }}
                            className="bg-error-container p-2 rounded-full border-2 border-on-surface shadow-[1px_1px_0px_0px_#1b1c1c] active:translate-y-0.5 duration-75 transition-transform cursor-pointer" 
                            title="一键标记已过期抛弃"
                          >
                            🗑️
                          </button>
                        </>
                      ) : (
                        <button 
                          onClick={() => onNavigateToTab('库存管理')}
                          className="bg-surface-container-high p-2.5 rounded-full border-2 border-on-surface shadow-[1px_1px_0px_0px_#1b1c1c] hover:translate-x-px duration-75 cursor-pointer"
                        >
                          <ChevronRight className="w-4 h-4 text-on-surface stroke-[3]" />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <button 
            onClick={() => onNavigateToTab('库存管理')}
            className="w-full mt-6 py-3 bg-on-surface text-white rounded-xl border-2 border-on-surface font-bold text-sm tracking-wider hover:bg-primary hover:shadow-[3px_3px_0px_0px_#1b1c1c] active:translate-y-px duration-75 cursor-pointer"
          >
            管理所有空间
          </button>
        </section>

        {/* Fun Mascot quote sticker card */}
        <div className="bg-white border-2 border-on-surface p-4 rounded-xl rotate-[1.5deg] relative overflow-hidden group hover:rotate-0 transition-all duration-300 shadow-[4px_4px_0px_0px_rgba(27,28,28,1)]">
          <img 
            alt="Organized nuts" 
            className="w-full h-36 object-cover rounded-lg border-2 border-on-surface mb-4" 
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuBrvL6Z9qWB64q_7NZjwUnb1OPePEf_SsNMPwMlOgniChblQS7ECnRsK5LI9ahwABdockbm2A5edXKwmyYXVE4K_gBEEwBUnGWlYQueowLAPIDC87dslBBpVLDTYU9IZ0Coa8s9UjrrYzsGh4MuoE4wD4IrHe_Ndjj5cr0h1pLRcRWuNkugRH8GItCL-oh_TT7jt6jHPRwgA0Ofi5jIeWiNZKWU6labtjbOPPiJfL2hg-DGPvwNsJjuv9q8L0QJMqP8MY3lCPiDd4yD"
            referrerPolicy="no-referrer"
          />
          <div className="font-bold text-primary flex items-center gap-1.5 text-sm">
            <span>🐿️ 松鼠的小贴士</span>
          </div>
          <p className="text-xs text-on-surface-variant font-medium mt-1">
            “别把坚果种子放进太潮湿的柜子里哦，除非你想在明天的厨房墙角里种树！呼！”
          </p>
        </div>
      </div>

      {/* --- Recipe steps popup detail model --- */}
      {showRecipeModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white border-2 border-on-surface rounded-2xl p-6 max-w-lg w-full shadow-[6px_6px_0px_0px_#1b1c1c] relative animate-in zoom-in-95 duration-100">
            <h2 className="text-xl font-bold text-primary mb-2">🍳 松鼠筑巢推荐烹饪纸草：{recipe.title}</h2>
            <div className="text-xs text-on-surface-variant mb-4 pb-2 border-b border-on-surface">
              {recipe.description}
            </div>

            <div className="mb-4">
              <h4 className="font-bold text-xs bg-tertiary-fixed text-on-tertiary-fixed px-2 py-0.5 rounded-full inline-block mb-1.5">准备食材</h4>
              <p className="text-xs font-semibold leading-relaxed p-2 bg-surface-container-low rounded-lg border border-on-surface">
                {recipe.ingredients}
              </p>
            </div>

            <div className="mb-6">
              <h4 className="font-bold text-xs bg-secondary-container text-on-secondary-container px-2 py-0.5 rounded-full inline-block mb-1.5">烹饪简易工序</h4>
              <ol className="list-decimal list-inside text-xs leading-relaxed space-y-2 font-medium">
                {recipe.steps ? recipe.steps.map((step: string, i: number) => (
                  <li key={i} className="pl-1 border-b border-dashed border-on-surface-variant/20 pb-1">{step}</li>
                )) : (
                  <li>起锅烧热，放入食材翻炒至熟即可盛出。</li>
                )}
              </ol>
            </div>

            <div className="flex justify-end gap-2">
              <button 
                onClick={() => {
                  alert("烹饪开始！系统将为您自动扣除对应食材的部分消耗百分比～🥞");
                  // Reduce relevant items
                  const bread = items.find(i => i.title.includes("面包"));
                  if (bread) onConsumeItem(bread.id, 25);
                  setShowRecipeModal(false);
                }}
                className="bg-secondary text-white px-6 py-2 rounded-full font-bold text-xs shadow-[2px_2px_0px_0px_#1b1c1c] hover:translate-y-0.5 duration-75 cursor-pointer"
              >
                开火，开始烹饪！
              </button>
              <button 
                onClick={() => setShowRecipeModal(false)}
                className="bg-white border border-on-surface px-4 py-2 rounded-full font-bold text-xs duration-75 cursor-pointer"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
