import React, { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Check, X, Package, Minus, Plus } from "lucide-react";
import { PendingItem } from "../types";

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
                      className="bg-surface border-2 border-on-background rounded-2xl p-4 shadow-[2px_3px_0_0_#1b1c1c]"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <p className="font-display font-bold text-sm text-on-background truncate">
                            {item.title}
                          </p>
                          <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5 text-xs text-outline">
                            {item.category && (
                              <span>分类：{item.category}</span>
                            )}
                            {item.location && (
                              <span>位置：{item.location}</span>
                            )}
                            {item.expireDate && (
                              <span>到期：{item.expireDate}</span>
                            )}
                          </div>
                          {item.remark && (
                            <p className="text-xs text-outline mt-1 truncate">
                              备注：{item.remark}
                            </p>
                          )}
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
