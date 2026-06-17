import React, { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Check, X, Package, Minus, Plus } from "lucide-react";
import { PendingItem, InventoryCategory } from "../types";
import { CATEGORY_MAP } from "../utils";

interface ConfirmModalProps {
  isOpen: boolean;
  pendingId: string;
  items: PendingItem[];
  onConfirm: (pendingId: string, items: PendingItem[]) => Promise<void>;
  onCancel: () => void;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  isOpen,
  pendingId,
  items,
  onConfirm,
  onCancel,
}) => {
  const [editItems, setEditItems] = useState<PendingItem[]>(items);
  const [isConfirming, setIsConfirming] = useState(false);

  // Reset editItems when items prop changes
  React.useEffect(() => {
    setEditItems(items);
  }, [items]);

  const updateItem = (index: number, field: keyof PendingItem, value: string | number) => {
    setEditItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [field]: value } : item))
    );
  };

  const updateCount = (index: number, delta: number) => {
    setEditItems((prev) =>
      prev.map((item, i) =>
        i === index
          ? { ...item, count: Math.max(1, item.count + delta) }
          : item
      )
    );
  };

  const handleConfirm = async () => {
    setIsConfirming(true);
    try {
      await onConfirm(pendingId, editItems);
    } finally {
      setIsConfirming(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/30 z-[9998]"
            onClick={onCancel}
          />

          {/* Modal */}
          <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 pointer-events-none">
            <motion.div
              initial={{ scale: 0.9, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.9, opacity: 0, y: 20 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              className="pointer-events-auto w-full max-w-md"
            >
              <div className="bg-white border-[3px] border-on-background shadow-[8px_10px_0_0_#1b1c1c] rounded-[32px] p-6 relative">
                {/* Close button */}
                <button
                  onClick={onCancel}
                  className="absolute top-4 right-4 p-1.5 hover:bg-black hover:bg-opacity-10 rounded-full transition-colors"
                  aria-label="关闭"
                >
                  <X size={18} className="text-on-background" />
                </button>

                {/* Header */}
                <div className="flex items-center gap-3 mb-5">
                  <div className="p-3 bg-[#98f28d] rounded-full border-2 border-on-background">
                    <Package className="text-primary stroke-[2.5]" size={28} />
                  </div>
                  <div>
                    <h3 className="font-display font-extrabold text-lg text-on-background">
                      确认入库
                    </h3>
                    <p className="text-xs text-outline">
                      识别到 {items.length} 件物品，确认后将加入库存
                    </p>
                  </div>
                </div>

                {/* Item list */}
                <div className="space-y-3 max-h-[360px] overflow-y-auto mb-5">
                  {editItems.map((item, index) => (
                    <div
                      key={index}
                      className="bg-surface border-2 border-on-background rounded-2xl p-4 shadow-[2px_3px_0_0_#1b1c1c] space-y-2.5"
                    >
                      {/* Title + Count row */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <input
                            type="text"
                            value={item.title}
                            onChange={(e) => updateItem(index, "title", e.target.value)}
                            disabled={isConfirming}
                            className="w-full font-display font-bold text-sm text-on-background bg-white border-2 border-on-background rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
                            placeholder="物品名称"
                          />
                        </div>

                        {/* Count adjuster */}
                        <div className="flex items-center gap-1.5 bg-white border-2 border-on-background rounded-xl px-2 py-1 shrink-0">
                          <button
                            onClick={() => updateCount(index, -1)}
                            className="p-1 hover:bg-surface rounded-lg transition-colors"
                            disabled={isConfirming}
                          >
                            <Minus size={14} className="text-on-background" />
                          </button>
                          <span className="font-display font-extrabold text-sm w-8 text-center text-on-background">
                            {item.count}
                          </span>
                          <button
                            onClick={() => updateCount(index, 1)}
                            className="p-1 hover:bg-surface rounded-lg transition-colors"
                            disabled={isConfirming}
                          >
                            <Plus size={14} className="text-on-background" />
                          </button>
                          <span className="text-xs text-outline ml-0.5">
                            {item.unit}
                          </span>
                        </div>
                      </div>

                      {/* Category & Location row */}
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="text-[10px] text-outline mb-0.5 block">分类</label>
                          <select
                            value={item.category}
                            onChange={(e) => updateItem(index, "category", e.target.value)}
                            disabled={isConfirming}
                            className="w-full text-xs p-1.5 border-2 border-on-background rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer disabled:opacity-60"
                          >
                            {Object.entries(CATEGORY_MAP).map(([key, meta]) => (
                              <option key={key} value={key}>
                                {meta.chineseName}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="text-[10px] text-outline mb-0.5 block">位置</label>
                          <input
                            type="text"
                            value={item.location}
                            onChange={(e) => updateItem(index, "location", e.target.value)}
                            disabled={isConfirming}
                            className="w-full text-xs p-1.5 border-2 border-on-background rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
                            placeholder="存放位置"
                          />
                        </div>
                      </div>

                      {/* Expire date & Remark row */}
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="text-[10px] text-outline mb-0.5 block">到期时间</label>
                          <input
                            type="date"
                            value={item.expireDate || ""}
                            onChange={(e) => updateItem(index, "expireDate", e.target.value)}
                            disabled={isConfirming}
                            className="w-full text-xs p-1.5 border-2 border-on-background rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer disabled:opacity-60"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] text-outline mb-0.5 block">备注</label>
                          <input
                            type="text"
                            value={item.remark || ""}
                            onChange={(e) => updateItem(index, "remark", e.target.value)}
                            disabled={isConfirming}
                            className="w-full text-xs p-1.5 border-2 border-on-background rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
                            placeholder="备注信息"
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Actions */}
                <div className="flex gap-3">
                  <button
                    onClick={onCancel}
                    disabled={isConfirming}
                    className="flex-1 py-3 px-4 bg-[#ece7e8] hover:bg-white border-2 border-on-background rounded-full font-display font-bold text-sm text-on-background shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer disabled:opacity-50"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleConfirm}
                    disabled={isConfirming}
                    className="flex-1 py-3 px-4 bg-primary hover:bg-primary-container border-2 border-on-background rounded-full font-display font-bold text-sm text-white shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    <Check size={16} />
                    {isConfirming ? "入库中..." : "确认入库"}
                  </button>
                </div>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
};
