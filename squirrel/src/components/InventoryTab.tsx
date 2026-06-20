import React, { useState } from "react";
import { InventoryItem, InventoryCategory, AppSettings } from "../types";
import { getItemStatus, CATEGORY_MAP } from "../utils";
import { Modal } from "./Modal";
import {
  Search, SlidersHorizontal, Plus, Calendar,
  MapPin, Tag, MoreVertical, X, AlertTriangle, Trash2,
  Minus, Plus as PlusIcon
} from "lucide-react";

interface InventoryProps {
  items: InventoryItem[];
  settings: AppSettings;
  onViewItem: (item: InventoryItem) => void;
  onEditItem: (item: InventoryItem) => void;
  onQuickCleanItem: (id: string, consumeCount?: number) => Promise<void> | void;
  onCreateNewItem: () => void;
}

export const InventoryTab: React.FC<InventoryProps> = ({
  items,
  settings,
  onViewItem,
  onEditItem,
  onQuickCleanItem,
  onCreateNewItem,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedCat, setSelectedCat] = useState<string>("all");
  const [selectedLoc, setSelectedLoc] = useState<string>("all");
  const [sortBy, setSortBy] = useState<'expiry' | 'quantity' | 'name'>('expiry');

  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    itemId: string;
    itemName: string;
    itemQuantity: number;
    itemUnit: string;
  }>({ isOpen: false, itemId: "", itemName: "", itemQuantity: 1, itemUnit: "个" });

  const [consumeCount, setConsumeCount] = useState(1);

  const [alertModal, setAlertModal] = useState<{
    isOpen: boolean;
    message: string;
  }>({ isOpen: false, message: "" });

  const strategy = settings.expirationStrategy;

  // Render categories selection
  const categoriesList = [
    { key: "all", label: "🎒 全部" },
    { key: "food", label: "🍎 食珍" },
    { key: "medicine", label: "💊 药箱" },
    { key: "electronics", label: "🔌 外设" },
    { key: "cosmetics", label: "🧴 护理" },
    { key: "book", label: "📚 书阁" },
    { key: "other", label: "📦 杂物" }
  ];

  // Render locations selection
  const locationsList = ["all", ...settings.selectedLocations];

  // Filter items
  const filteredItems = items.filter((item) => {
    const textMatch = 
      item.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      item.tags.some(t => t.toLowerCase().includes(searchTerm.toLowerCase())) ||
      (item.note && item.note.toLowerCase().includes(searchTerm.toLowerCase()));

    const catMatch = selectedCat === "all" || item.category === selectedCat;
    const locMatch = selectedLoc === "all" || item.location === selectedLoc;

    return textMatch && catMatch && locMatch;
  });

  // Sort items
  const sortedItems = [...filteredItems].sort((a, b) => {
    if (sortBy === "expiry") {
      // items without expiryDate go last
      if (!a.expiryDate && !b.expiryDate) return a.name.localeCompare(b.name);
      if (!a.expiryDate) return 1;
      if (!b.expiryDate) return -1;
      return new Date(a.expiryDate).getTime() - new Date(b.expiryDate).getTime();
    } else if (sortBy === "quantity") {
      return b.quantity - a.quantity;
    } else {
      return a.name.localeCompare(b.name);
    }
  });

  return (
    <div className="space-y-7 relative min-h-[500px] select-none">
      {/* Search and Filters panel */}
      <div className="bg-white border-[3px] border-on-background shadow-[4px_5px_0_0_#1b1c1c] rounded-[28px] p-4 space-y-4">
        {/* Search Input and Sort selects */}
        <div className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 text-outline" size={17} />
            <input
              type="text"
              placeholder="搜一搜存根，如‘牛奶’、‘感冒药’或标签‘#breakfast’..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 bg-surface border-[3px] border-on-background rounded-full text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:bg-white"
            />
            {searchTerm && (
              <button 
                onClick={() => setSearchTerm("")}
                className="absolute right-3 top-3 text-outline hover:text-on-background"
              >
                <X size={16} />
              </button>
            )}
          </div>

          <div className="flex gap-2 shrink-0">
            <div className="flex items-center gap-1.5 bg-[#ece7e8] border-[3px] border-on-background px-3 py-1.5 rounded-full text-xs font-display shadow-[2px_3px_0_0_#1b1c1c]">
              <SlidersHorizontal size={14} className="text-outline" />
              <span>排序</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as any)}
                className="bg-transparent border-none font-bold focus:outline-none cursor-pointer"
              >
                <option value="expiry">临保期限</option>
                <option value="quantity">囤积数量</option>
                <option value="name">字词名称</option>
              </select>
            </div>

            <button
              onClick={onCreateNewItem}
              className="md:hidden flex items-center gap-1 bg-primary text-white border-2 border-on-background px-4 py-1.5 rounded-full text-xs font-display font-bold shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer"
            >
              <Plus size={14} /> 录入
            </button>
          </div>
        </div>

        {/* Category filtering pills */}
        <div className="space-y-1.5">
          <label className="text-[11px] font-bold text-outline block">物品大类筛选:</label>
          <div className="flex flex-wrap gap-1.5">
            {categoriesList.map((cat) => {
              const isSelected = selectedCat === cat.key;
              return (
                <button
                  key={cat.key}
                  onClick={() => setSelectedCat(cat.key)}
                  className={`px-3 py-1.5 text-xs font-bold border-2 border-on-background rounded-full active-press transition-colors cursor-pointer ${
                    isSelected 
                      ? "bg-primary text-white shadow-[2px_3px_0_0_#1b1c1c]" 
                      : "bg-surface text-on-background hover:bg-[#ffe92e]"
                  }`}
                >
                  {cat.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Location selection slider */}
        <div className="space-y-1.5 pt-1.5 border-t border-surface-container">
          <label className="text-[11px] font-bold text-outline block">储藏角落筛选:</label>
          <div className="flex flex-wrap gap-1.5">
            {locationsList.map((loc) => {
              const isSelected = selectedLoc === loc;
              return (
                <button
                  key={loc}
                  onClick={() => setSelectedLoc(loc)}
                  className={`px-3.5 py-1 text-xs border-2 border-on-background rounded-full active-press-sm transition-colors cursor-pointer ${
                    isSelected 
                      ? "bg-[#98f28d] text-on-background shadow-[2px_3px_0_0_#1b1c1c] font-bold" 
                      : "bg-surface text-on-background hover:bg-[#ffe92e] font-medium"
                  }`}
                >
                  {loc === "all" ? "🌲 全部角落" : `📍 ${loc}`}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Main Stock Item Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {sortedItems.map((item) => {
          const catMeta = CATEGORY_MAP[item.category];
          const expInfo = getItemStatus(item, strategy);
          const isExpired = expInfo.status === "expired";
          const isWarning = expInfo.status === "warning";
          const isFresh = expInfo.status === "fresh";

          return (
            <div
              key={item.id}
              onClick={() => onViewItem(item)}
              className="bg-white border-[3px] border-on-background shadow-[3px_4px_0_0_#1b1c1c] rounded-[28px] p-4 flex flex-col justify-between hover:-translate-y-0.5 transition-transform active:scale-[0.99] cursor-pointer relative"
            >
              {/* Top Row Category & Expiry status */}
              <div className="flex items-start justify-between gap-2 mb-3">
                <span className={`text-[10px] font-bold px-2 py-0.5 border-2 border-on-background rounded-full leading-none ${catMeta.bgColor} ${catMeta.textColor}`}>
                  {catMeta.chineseName}
                </span>

                <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full border-2 border-on-background leading-none ${
                  isExpired 
                    ? "bg-red-500 text-white" 
                    : isWarning 
                        ? "bg-[#ffe92e] text-[#665800] border-[#8f7a00]" 
                      : isFresh 
                        ? "bg-[#98f28d] text-[#0f5c1d] border-[#18822a]"
                        : "bg-[#ece7e8] text-[#694f54] border-[#7b6165]"
                }`}>
                  {expInfo.displayText}
                </span>
              </div>

              {/* Central Title */}
              <div className="space-y-1 mb-3">
                <h4 className="font-display font-bold text-on-background text-base flex items-baseline gap-1.5 leading-snug">
                  <span className="hover:underline">{item.name}</span>
                  <span className="text-xs bg-[#ffe92e] px-1.5 py-0.5 border border-on-background rounded font-mono font-normal">
                    {item.quantity}{item.unit}
                  </span>
                </h4>

                {item.note && (
                  <p className="text-xs text-outline line-clamp-2 italic leading-relaxed">
                    “ {item.note} ”
                  </p>
                )}
              </div>

              {/* Bottom Row Locations and Tags */}
              <div className="pt-3 border-t border-dashed border-outline-variant space-y-2">
                <div className="flex items-center text-[11px] text-outline gap-1 leading-none">
                  <MapPin size={11} className="text-secondary shrink-0" />
                  <span className="truncate">{item.location}</span>
                </div>

                {item.tags && item.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {item.tags.map((t) => (
                      <span key={t} className="text-[10px] text-outline bg-[#ece7e8] px-1 rounded-full leading-none py-0.5">
                        #{t}
                      </span>
                    ))}
                  </div>
                )}

                {/* Quick clean button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setConsumeCount(1);
                    setConfirmModal({
                      isOpen: true,
                      itemId: item.id,
                      itemName: item.name,
                      itemQuantity: item.quantity,
                      itemUnit: item.unit,
                    });
                  }}
                  className="mt-2 px-2.5 py-1 bg-[#ffd5d1] hover:bg-[#ffe9e6] border-2 border-on-background text-[10px] text-error font-bold rounded-full cursor-pointer"
                  title="标记吃完/清理"
                >
                  吃完/清掉
                </button>
              </div>
            </div>
          );
        })}

        {/* Empty state illustration */}
        {sortedItems.length === 0 && (
          <div className="col-span-1 sm:col-span-2 lg:col-span-3 p-12 text-center bg-white border-[3px] border-dashed border-outline-variant rounded-[28px]">
            <span className="text-5xl block mb-3 animate-pulse">🌰</span>
            <p className="font-display font-bold text-on-background text-base">空空如也的树洞</p>
            <p className="text-xs text-outline mt-1 max-w-sm mx-auto">
              没有发现任何存根档案吱。快点击右下角那个闪亮的“录入归巢”魔法加号，或者直接拍照/向松鼠求助！
            </p>
          </div>
        )}
      </div>

      {/* Modals */}
      <Modal
        isOpen={confirmModal.isOpen}
        onClose={() => setConfirmModal({ isOpen: false, itemId: "", itemName: "", itemQuantity: 1, itemUnit: "个" })}
        onConfirm={() => {
          const count = confirmModal.itemQuantity > 1 ? consumeCount : undefined;
          void Promise.resolve(onQuickCleanItem(confirmModal.itemId, count)).catch((error) => {
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
        confirmText={confirmModal.itemQuantity > 1 && consumeCount < confirmModal.itemQuantity ? `消耗 ${consumeCount}${confirmModal.itemUnit}` : "确认清理"}
        cancelText="再想想"
      >
        {confirmModal.itemQuantity > 1 ? (
          <div className="space-y-3">
            <p className="text-sm text-on-background leading-relaxed px-2">
              吱！【{confirmModal.itemName}】还有 <strong>{confirmModal.itemQuantity}{confirmModal.itemUnit}</strong>，要消耗多少呢？
            </p>

            {/* Consume all toggle */}
            <label className="flex items-center justify-between p-3 border-2 border-on-background rounded-xl bg-surface cursor-pointer mx-2">
              <div className="flex items-center gap-2">
                <Trash2 size={14} className="text-red-600" />
                <span className="text-sm font-display font-bold text-on-background">
                  全部清除
                </span>
              </div>
              <input
                type="checkbox"
                checked={consumeCount >= confirmModal.itemQuantity}
                onChange={(e) => setConsumeCount(e.target.checked ? confirmModal.itemQuantity : 1)}
                className="w-4 h-4 rounded border-2 border-on-background accent-primary"
              />
            </label>

            {/* Partial consume count stepper */}
            {consumeCount < confirmModal.itemQuantity && (
              <div className="flex items-center justify-between p-3 border-2 border-on-background rounded-xl bg-white mx-2">
                <span className="text-sm text-on-background">消耗数量</span>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setConsumeCount(Math.max(1, consumeCount - 1))}
                    className="p-1 hover:bg-surface rounded-lg transition-colors"
                  >
                    <Minus size={14} className="text-on-background" />
                  </button>
                  <span className="font-display font-extrabold text-sm w-8 text-center text-on-background">
                    {consumeCount}
                  </span>
                  <button
                    onClick={() => setConsumeCount(Math.min(confirmModal.itemQuantity, consumeCount + 1))}
                    className="p-1 hover:bg-surface rounded-lg transition-colors"
                  >
                    <PlusIcon size={14} className="text-on-background" />
                  </button>
                  <span className="text-xs text-outline ml-0.5">
                    {confirmModal.itemUnit}
                  </span>
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-on-background leading-relaxed px-2">
            吱！您确定已经吃完或清理了【{confirmModal.itemName}】，并从清单中删除吗？
          </p>
        )}
      </Modal>

      <Modal
        isOpen={alertModal.isOpen}
        onClose={() => setAlertModal({ isOpen: false, message: "" })}
        type="alert"
        variant="danger"
        message={alertModal.message}
      />

      {/* Desktop Floating Action Button */}
      <button
        onClick={onCreateNewItem}
        className="fixed bottom-6 right-6 w-14 h-14 bg-primary hover:bg-primary-container text-white border-4 border-on-background rounded-full flex items-center justify-center shadow-[4px_5px_0_0_#1b1c1c] active-press cursor-pointer z-30"
        title="筑巢登记 - 新增物品"
        id="desktop-floating-fab"
      >
        <Plus size={28} className="stroke-[3]" />
      </button>
    </div>
  );
};
