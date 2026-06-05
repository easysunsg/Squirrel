import React, { useState } from 'react';
import { Item, Space } from '../types';
import { Search, Plus, MapPin, Calendar, Clock, Percent, FileText, ShoppingCart, Trash2, X, PlusCircle, Check, Sparkles, Filter, ChevronRight } from 'lucide-react';

interface InventoryViewProps {
  items: Item[];
  spaces: Space[];
  onUpdateItem: (id: string, updated: Partial<Item>) => void;
  onDeleteItem: (id: string) => void;
  onAddItem: (item: Partial<Item>) => void;
}

export default function InventoryView({
  items,
  spaces,
  onUpdateItem,
  onDeleteItem,
  onAddItem
}: InventoryViewProps) {
  const [selectedFilter, setSelectedFilter] = useState<string>('全部物品');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [activeDetailItem, setActiveDetailItem] = useState<Item | null>(null);
  const [showAddModal, setShowAddModal] = useState<boolean>(false);

  // New item form state
  const [newItemTitle, setNewItemTitle] = useState('');
  const [newItemSpace, setNewItemSpace] = useState('kitchen');
  const [newItemLocation, setNewItemLocation] = useState('');
  const [newItemCount, setNewItemCount] = useState(1);
  const [newItemUnit, setNewItemUnit] = useState('个');
  const [newItemPct, setNewItemPct] = useState(100);
  const [newItemExpire, setNewItemExpire] = useState('2026-12-31');

  const filters = ['全部物品', '主厨房', '储藏间', '车库工具', '告急/过期'];

  // Filtering items based on category tabs & search raw query
  const filteredItems = items.filter(item => {
    // 1. Tag filters
    if (selectedFilter === '主厨房' && item.spaceName !== '主厨房') return false;
    if (selectedFilter === '储藏间' && item.spaceName !== '储藏间') return false;
    if (selectedFilter === '车库工具' && item.spaceName !== '车库工具') return false;
    if (selectedFilter === '告急/过期' && item.tag !== '告急' && item.tag !== '过期预警') return false;

    // 2. Search query matching
    if (searchQuery.trim() !== '') {
      const q = searchQuery.toLowerCase();
      return (
        item.title.toLowerCase().includes(q) ||
        item.location.toLowerCase().includes(q) ||
        (item.remark && item.remark.toLowerCase().includes(q))
      );
    }

    return true;
  });

  const getTagColor = (tag: string) => {
    switch (tag) {
      case '告急':
      case '过期预警':
        return 'bg-error-container text-error border-error';
      case '较低':
        return 'bg-tertiary-fixed text-on-tertiary-fixed border-tertiary';
      case '充足':
      default:
        return 'bg-secondary-container text-on-secondary-container border-secondary';
    }
  };

  const getItemEmoji = (icon: string, title?: string) => {
    const t = title || '';
    if (t.includes('面包')) return '🥖';
    if (t.includes('工具') || t.includes('螺丝') || icon === 'construction') return '🔧';
    if (t.includes('贴') || t.includes('纸') || icon === 'edit_note') return '📝';
    if (t.includes('咖啡') || icon === 'local_cafe') return '☕';
    if (t.includes('洗洁') || icon === 'cleaning_services') return '🧴';
    if (t.includes('维C') || t.includes('药') || icon === 'medication') return '💊';
    return '📦';
  };

  // Submit manual creation
  const handleCreateItemSubmit = () => {
    if (!newItemTitle.trim()) {
      alert("请输入物品名称！");
      return;
    }

    const matchedSpace = spaces.find(s => s.id === newItemSpace);
    const spaceName = matchedSpace ? matchedSpace.name : '主厨房';

    onAddItem({
      title: newItemTitle,
      spaceId: newItemSpace,
      spaceName: spaceName,
      location: newItemLocation || '默认层架',
      count: Number(newItemCount) || 1,
      unit: newItemUnit || '个',
      remainingPct: Number(newItemPct),
      buyDate: new Date().toISOString().split('T')[0],
      expireDate: newItemExpire || '2026-12-31',
      tag: newItemPct < 20 ? '告急' : (newItemPct < 50 ? '较低' : '充足'),
      icon: newItemSpace === 'garage' ? 'construction' : (newItemSpace === 'storage' ? 'shelves' : 'kitchen'),
      remark: '手工录入添加归档。'
    });

    // Reset Form
    setNewItemTitle('');
    setNewItemLocation('');
    setNewItemCount(1);
    setNewItemPct(100);
    setShowAddModal(false);
  };

  return (
    <div className="max-w-6xl mx-auto mt-6 pb-12 relative">
      
      {/* Top Search bar & Tabs filtering box row */}
      <div className="flex flex-col md:flex-row gap-4 justify-between items-center bg-white border-2 border-on-surface p-4 rounded-xl shadow-[3px_3px_0px_0px_rgba(27,28,28,1)] mb-6 select-none">
        
        {/* Navigation badges matching style */}
        <div className="flex flex-wrap gap-2 w-full md:w-auto">
          {filters.map((filter) => {
            const isSelected = selectedFilter === filter;
            return (
              <button
                key={filter}
                onClick={() => setSelectedFilter(filter)}
                className={`px-4 py-2 rounded-full text-xs font-black border-2 border-on-surface transition-all cursor-pointer ${
                  isSelected 
                    ? 'bg-primary text-white shadow-[1px_1px_0px_0px_#000] translate-y-px' 
                    : 'bg-white hover:bg-surface-container-low'
                }`}
              >
                {filter === '全部物品' ? '📂 全部物品' : 
                 filter === '主厨房' ? '🥛 主厨房' : 
                 filter === '储藏间' ? '📦 储藏间' : 
                 filter === '车库工具' ? '🔧 车库工具' : '🚨 告急/过期'}
              </button>
            );
          })}
        </div>

        {/* Input box */}
        <div className="relative w-full md:w-64">
          <input
            type="text"
            placeholder="搜索松鼠洞物品/位置..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 border-2 border-on-surface rounded-full text-xs focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary font-bold"
          />
          <Search className="w-4 h-4 text-on-surface-variant absolute left-3 top-2.5" />
        </div>
      </div>

      {/* Main Grid content items list */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-6">
        {filteredItems.map((item) => {
          const emoji = getItemEmoji(item.icon, item.title);
          
          return (
            <div
              key={item.id}
              onClick={() => setActiveDetailItem(item)}
              className={`bg-[#fdfbf7] border-2 border-on-surface rounded-2xl p-5 shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] hover:scale-[1.02] active:scale-[0.98] transition-all cursor-pointer flex flex-col justify-between h-48 group relative overflow-hidden`}
              id={`item-card-${item.id}`}
            >
              {/* Hand-drawn look pattern stripes */}
              <div className="absolute top-0 right-0 w-8 h-8 opacity-10 bg-radial-gradient from-on-surface/50 to-transparent pointer-events-none" />

              <div>
                <div className="flex justify-between items-start mb-3">
                  <div className="flex items-center gap-2.5">
                    <span className="text-3xl bg-white p-1 rounded-xl border border-on-surface shadow-[1px_1px_0px_0px_#1b1c1c]">{emoji}</span>
                    <div>
                      <h3 className="font-extrabold text-base text-on-surface tracking-tight group-hover:text-primary transition-colors">{item.title}</h3>
                      <div className="flex items-center gap-1 text-[10px] text-on-surface-variant font-black">
                        <MapPin className="w-3 h-3 text-red-500" /> {item.location}
                      </div>
                    </div>
                  </div>

                  <span className={`text-[10px] font-black px-2 py-0.5 rounded-full border ${getTagColor(item.tag)}`}>
                    {item.tag}
                  </span>
                </div>

                <p className="text-xs text-on-surface-variant/80 line-clamp-1 font-semibold mb-4 pr-4">
                  {item.remark || '暂无小松鼠备注信息。'}
                </p>
              </div>

              {/* Progress remaining slider visualization */}
              <div className="space-y-1">
                <div className="flex justify-between text-[10px] font-black">
                  <span className="text-on-surface-variant">剩余量: {item.count}{item.unit}</span>
                  <span className={item.remainingPct <= 20 ? 'text-error animate-pulse' : 'text-on-surface-variant'}>
                    {item.remainingPct}%
                  </span>
                </div>
                <div className="w-full h-3.5 bg-white border-2 border-on-surface rounded-full p-0.5 overflow-hidden">
                  <div 
                    className={`h-full rounded-full transition-all duration-500 ${
                      item.remainingPct <= 20 ? 'bg-error' : (item.remainingPct <= 50 ? 'bg-tertiary shadow-xl' : 'bg-secondary')
                    }`}
                    style={{ width: `${item.remainingPct}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}

        {filteredItems.length === 0 && (
          <div className="col-span-full py-16 bg-white border-2 border-dashed border-on-surface/40 rounded-2xl text-center shadow-[4px_4px_0px_0px_#1b1c1c] p-6 max-w-sm mx-auto">
            <span className="text-5xl">🔭</span>
            <h4 className="text-sm font-black mt-4">这里空无一物...</h4>
            <p className="text-xs text-on-surface-variant mt-2 font-medium">
              小松鼠搜寻了整块洞壁层架，没有找到符合当前过滤条件的物品记录噢。
            </p>
            <button 
              onClick={() => setSelectedFilter('全部物品')}
              className="mt-4 px-4 py-1.5 bg-primary text-white text-xs rounded-full border border-on-surface font-extrabold shadow-[1px_1px_0px_0px_#000] cursor-pointer"
            >
              清除过滤
            </button>
          </div>
        )}

        {/* Wide seasonal summary banner matching card at bottom of grid */}
        <div className="col-span-full bg-secondary-fixed border-2 border-on-surface p-6 rounded-2xl shadow-[4px_4px_0px_0px_rgba(27,28,28,1)] flex flex-col md:flex-row gap-6 items-center mt-6">
          <img 
            alt="Squirrel tidying" 
            className="w-full md:w-1/3 h-40 object-cover rounded-xl border border-on-surface" 
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuBoPhESGTYP3GUAiYTau0y0nZKLASC3CGFMhxU6qITfnldHE95VJYlVKSbB9HvHjiMk6nTcnF8Enc1rOiHQ8QAKqhoXCSsA6pzRXduFt-FYD0RILbD2-IvfqKOnhievROA3aN_3S3Kz48B0-a_9yTfkLi4BjQUP74r_xsX36UBSproGcwzUtZq0QvmSiRuj4TsQi99qAaHcn2jBdzWVEkprytD4ALr6sswRrU4CbrcfkWtJtY0CbAEd-NXwOldf7uNO6S3gCTytsZUJ"
            referrerPolicy="no-referrer"
          />
          <div className="flex-1 space-y-2 text-center md:text-left">
            <h4 className="text-lg md:text-xl font-headline-lg font-black text-on-secondary-fixed">物品档案库 季节性整理提醒</h4>
            <p className="text-xs md:text-sm text-on-secondary-fixed-variant leading-relaxed font-semibold">
              小松鼠正计划在六月中旬梅雨前，进行全面的家庭防潮清算！建议提前排查主车库与储物盒，将带金属的防寒设备和快过期的食品转移至离地货架。
            </p>
            <div className="pt-2">
              <span className="bg-on-secondary-fixed text-white px-3 py-1 rounded-full text-[10px] font-bold shadow-[1.5px_1.5px_0px_0px_#1b1c1c]">梅雨防潮季 · 六月中旬开启</span>
            </div>
          </div>
        </div>

      </div>

      {/* Slide-out Closet Details Drawer Panel Overlay */}
      {activeDetailItem && (
        <div className="fixed inset-0 bg-black/40 z-50 flex justify-end">
          {/* Backdrop Clicker */}
          <div className="absolute inset-0 cursor-pointer" onClick={() => setActiveDetailItem(null)} />
          
          <div className="bg-[#fcfaf4] w-full max-w-md h-full border-l-4 border-on-surface relative p-6 flex flex-col justify-between shadow-[-10px_0px_0px_0px_rgba(27,28,28,0.15)] z-10 animate-in slide-in-from-right duration-250">
            <div>
              <div className="flex justify-between items-center border-b-2 border-on-surface pb-4 mb-6">
                <div className="flex items-center gap-3">
                  <span className="text-4xl">{getItemEmoji(activeDetailItem.icon, activeDetailItem.title)}</span>
                  <div>
                    <h2 className="text-xl font-headline-lg font-black text-on-surface">{activeDetailItem.title}</h2>
                    <span className="text-xs font-mono font-bold text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded-full border border-on-surface">ID: {activeDetailItem.id}</span>
                  </div>
                </div>
                <button 
                  onClick={() => setActiveDetailItem(null)}
                  className="bg-white border-2 border-on-surface p-1.5 rounded-full shadow-[2px_2px_0px_0px_#222] hover:translate-y-px group cursor-pointer"
                >
                  <X className="w-5 h-5 text-on-surface group-hover:text-red-500" />
                </button>
              </div>

              {/* Form entries list */}
              <div className="space-y-6">
                <div>
                  <h4 className="text-xs font-black text-on-surface-variant uppercase tracking-wider mb-2">📦 筑巢具体物理位置</h4>
                  <div className="flex items-center gap-3 bg-white p-3 rounded-xl border-2 border-on-surface shadow-[1.5px_1.5px_0px_0px_#000]">
                    <MapPin className="text-red-500 w-5 h-5" />
                    <input 
                      type="text" 
                      value={activeDetailItem.location}
                      onChange={(e) => onUpdateItem(activeDetailItem.id, { location: e.target.value })}
                      className="font-bold text-sm w-full outline-none focus:ring-0"
                    />
                  </div>
                </div>

                <div>
                  <h4 className="text-xs font-black text-on-surface-variant uppercase tracking-wider mb-2">📅 购买日期 / 预计过期日期</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-white p-3 rounded-xl border-2 border-on-surface text-center">
                      <span className="text-[10px] text-on-surface-variant block mb-1">物理入仓日</span>
                      <input 
                        type="date"
                        value={activeDetailItem.buyDate}
                        onChange={(e) => onUpdateItem(activeDetailItem.id, { buyDate: e.target.value })}
                        className="text-xs font-extrabold w-full text-center outline-none"
                      />
                    </div>
                    <div className="bg-white p-3 rounded-xl border-2 border-on-surface text-center">
                      <span className="text-[10px] text-on-surface-variant block mb-1">保质大限</span>
                      <input 
                        type="date"
                        value={activeDetailItem.expireDate}
                        onChange={(e) => onUpdateItem(activeDetailItem.id, { expireDate: e.target.value })}
                        className="text-xs font-extrabold w-full text-center outline-none"
                      />
                    </div>
                  </div>
                  <div className="text-[10px] text-red-500 font-bold mt-2 flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" /> 剩余有效期请关注仪表盘红色/橙色警告。
                  </div>
                </div>

                {/* Capacity interactive slide handle config */}
                <div>
                  <div className="flex justify-between items-center mb-2">
                    <h4 className="text-[11px] font-black text-on-surface-variant uppercase tracking-wider">🥫 拖动更新巢里剩余量</h4>
                    <span className="bg-primary text-white text-xs font-bold px-2 py-0.5 rounded-full border border-black">
                      剩余 {activeDetailItem.remainingPct}% ({activeDetailItem.count}{activeDetailItem.unit})
                    </span>
                  </div>

                  <div className="bg-white p-5 rounded-xl border-2 border-on-surface shadow-[2px_2px_0px_0px_#000]">
                    <input 
                      type="range"
                      min="0"
                      max="100"
                      step="5"
                      value={activeDetailItem.remainingPct}
                      onChange={(e) => {
                        const pct = Number(e.target.value);
                        let tag: '告急' | '较低' | '充足' = '充足';
                        if (pct < 20) tag = '告急';
                        else if (pct < 50) tag = '较低';
                        onUpdateItem(activeDetailItem.id, { remainingPct: pct, tag });
                      }}
                      className="w-full h-3.5 bg-surface-container-high rounded-full cursor-pointer accent-primary border border-on-surface"
                    />
                    <div className="flex justify-between mt-3 text-[10px] text-on-surface-variant font-bold">
                      <span>已断粮 (0%)</span>
                      <span>刚好过半分 (50%)</span>
                      <span>满当当 (100%)</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Action buttons at bottom of drawer */}
            <div className="space-y-3">
              <button
                onClick={() => {
                  alert(`已记入松鼠筑巢电子备忘清单！在下次汇总时小松鼠会通知您购买：${activeDetailItem.title} 🛒`);
                  setActiveDetailItem(null);
                }}
                className="w-full py-3 bg-secondary text-white rounded-xl font-bold text-xs border-2 border-on-surface flex items-center justify-center gap-2 shadow-[2px_2px_0px_0px_rgba(27,28,28,1)] hover:translate-y-px duration-75 cursor-pointer"
              >
                <ShoppingCart className="w-4 h-4 text-white" />
                加入采购清单
              </button>

              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => {
                    onUpdateItem(activeDetailItem.id, { remainingPct: 0, tag: '告急' });
                    alert(`已一键标记为已食用/消耗空！快呼叫松鼠补货啦 🥞`);
                    setActiveDetailItem(null);
                  }}
                  className="py-2.5 bg-white border-2 border-on-surface rounded-xl font-bold text-[10px] shadow-[1.5px_1.5px_0px_0px_#000] hover:translate-y-px duration-75 cursor-pointer"
                >
                  🧹 标记为空洞
                </button>
                <button
                  onClick={() => {
                    if (confirm(`确定要移除 "${activeDetailItem.title}" 物品在巢里的档案记录吗？`)) {
                      onDeleteItem(activeDetailItem.id);
                      setActiveDetailItem(null);
                      alert("已彻底删除对应的物品档案！");
                    }
                  }}
                  className="py-2.5 bg-error-container text-error border-2 border-error rounded-xl font-bold text-[10px] shadow-[1.5px_1.5px_0px_0px_#000] hover:translate-y-px duration-75 cursor-pointer"
                >
                  🗑️ 删除此档案
                </button>
              </div>
            </div>

          </div>
        </div>
      )}

      {/* Add Item Floating Action trigger button */}
      <button 
        onClick={() => setShowAddModal(true)}
        className="fixed bottom-8 right-8 bg-primary hover:bg-secondary text-white p-5 rounded-full border-4 border-on-surface shadow-[6px_6px_0px_0px_rgba(27,28,28,1)] hover:scale-105 active:scale-95 transition-all outline-none cursor-pointer z-40 animate-bounce"
        id="add-item-floating-btn"
        title="手工快速添加物品档案"
      >
        <Plus className="w-8 h-8 stroke-[4]" />
      </button>

      {/* --- Add popup Dialog Modal --- */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white border-2 border-on-surface rounded-2xl p-6 max-w-md w-full shadow-[6px_6px_0px_0px_#1b1c1c] relative animate-in zoom-in-95 duration-120 select-none">
            
            <div className="flex justify-between items-center border-b-2 border-on-surface pb-3 mb-4">
              <h3 className="font-extrabold text-lg flex items-center gap-1.5 text-primary">🐿️ 新物品筑巢凭照</h3>
              <button 
                onClick={() => setShowAddModal(false)}
                className="p-1 hover:bg-surface-container rounded-full"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4 text-xs font-semibold">
              <div>
                <label className="block text-[11px] text-on-surface-variant font-black mb-1">物品品名 *</label>
                <input 
                  type="text" 
                  placeholder="例如：自制草莓酱"
                  value={newItemTitle} 
                  onChange={(e) => setNewItemTitle(e.target.value)}
                  className="w-full border-2 border-on-surface p-2.5 rounded-lg text-xs font-extrabold focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] text-on-surface-variant font-black mb-1">所属物理空间</label>
                  <select 
                    value={newItemSpace} 
                    onChange={(e) => setNewItemSpace(e.target.value)}
                    className="w-full border-2 border-on-surface p-2 rounded-lg text-xs font-extrabold focus:outline-none bg-white"
                  >
                    <option value="kitchen">主厨房</option>
                    <option value="storage">储藏间</option>
                    <option value="garage">车库工具</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] text-on-surface-variant font-black mb-1">具体格数位置</label>
                  <input 
                    type="text" 
                    placeholder="e.g. 冰箱二层"
                    value={newItemLocation} 
                    onChange={(e) => setNewItemLocation(e.target.value)}
                    className="w-full border-2 border-on-surface p-2 rounded-lg text-xs focus:outline-none"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-[11px] text-on-surface-variant font-black mb-1">数量</label>
                  <input 
                    type="number"
                    value={newItemCount} 
                    onChange={(e) => setNewItemCount(Number(e.target.value))}
                    className="w-full border-2 border-on-surface p-2 rounded-lg text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-on-surface-variant font-black mb-1">物理单位</label>
                  <input 
                    type="text" 
                    value={newItemUnit} 
                    onChange={(e) => setNewItemUnit(e.target.value)}
                    className="w-full border-2 border-on-surface p-2 rounded-lg text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-on-surface-variant font-black mb-1">剩余用量 %</label>
                  <input 
                    type="number"
                    min="1"
                    max="100"
                    value={newItemPct} 
                    onChange={(e) => setNewItemPct(Number(e.target.value))}
                    className="w-full border-2 border-on-surface p-2 rounded-lg text-xs"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] text-on-surface-variant font-black mb-1">预计保质期</label>
                <input 
                  type="date" 
                  value={newItemExpire} 
                  onChange={(e) => setNewItemExpire(e.target.value)}
                  className="w-full border-2 border-on-surface p-2 rounded-lg text-xs"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button 
                onClick={handleCreateItemSubmit}
                className="bg-primary text-white px-6 py-2 rounded-full font-bold text-xs shadow-[2px_2px_0px_0px_#1b1c1c] hover:translate-y-0.5 duration-75 cursor-pointer"
              >
                确认并归档
              </button>
              <button 
                onClick={() => setShowAddModal(false)}
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
