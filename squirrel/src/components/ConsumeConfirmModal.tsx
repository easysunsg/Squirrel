import React, { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Check, X, Trash2, Minus, Plus, PackageOpen } from "lucide-react";
import { ConsumeCandidate } from "../types";

interface ConsumeConfirmModalProps {
  isOpen: boolean;
  pendingId: string;
  candidates: ConsumeCandidate[];
  consumeAll: boolean;
  replyText: string;
  onConfirm: (
    pendingId: string,
    selectedIndex: number,
    consumeAll: boolean,
    count?: number
  ) => Promise<void>;
  onCancel: () => void;
}

export const ConsumeConfirmModal: React.FC<ConsumeConfirmModalProps> = ({
  isOpen,
  pendingId,
  candidates,
  consumeAll: initialConsumeAll,
  replyText,
  onConfirm,
  onCancel,
}) => {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [consumeAll, setConsumeAll] = useState(initialConsumeAll);
  const [consumeCount, setConsumeCount] = useState(1);
  const [isConfirming, setIsConfirming] = useState(false);

  React.useEffect(() => {
    setSelectedIndex(0);
    setConsumeAll(initialConsumeAll);
    setConsumeCount(1);
  }, [candidates, initialConsumeAll]);

  const selected = candidates[selectedIndex];

  const handleConfirm = async () => {
    setIsConfirming(true);
    try {
      await onConfirm(
        pendingId,
        selectedIndex,
        consumeAll,
        consumeAll ? undefined : consumeCount
      );
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
                  <div className="p-3 bg-[#ffdbd6] rounded-full border-2 border-on-background">
                    <PackageOpen className="text-red-600 stroke-[2.5]" size={28} />
                  </div>
                  <div>
                    <h3 className="font-display font-extrabold text-lg text-on-background">
                      确认消耗
                    </h3>
                    <p className="text-xs text-outline">{replyText}</p>
                  </div>
                </div>

                {/* Candidate list */}
                {candidates.length > 1 && (
                  <div className="space-y-2 max-h-[200px] overflow-y-auto mb-4">
                    {candidates.map((item, index) => (
                      <button
                        key={item.id || index}
                        onClick={() => setSelectedIndex(index)}
                        disabled={isConfirming}
                        className={`w-full text-left p-3 border-2 rounded-xl transition-colors ${
                          selectedIndex === index
                            ? "border-on-background bg-[#ffe92e] shadow-[2px_3px_0_0_#1b1c1c]"
                            : "border-outline-variant bg-surface hover:bg-surface-container"
                        }`}
                      >
                        <p className="font-display font-bold text-sm text-on-background">
                          {item.title}
                        </p>
                        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-xs text-outline">
                          <span>
                            {item.spaceName}/{item.location}
                          </span>
                          <span>
                            {item.count}
                            {item.unit}
                          </span>
                          <span>剩余 {item.remainingPct}%</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {/* Single item display */}
                {candidates.length === 1 && selected && (
                  <div className="bg-surface border-2 border-on-background rounded-2xl p-4 mb-4 shadow-[2px_3px_0_0_#1b1c1c]">
                    <p className="font-display font-bold text-sm text-on-background">
                      {selected.title}
                    </p>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5 text-xs text-outline">
                      <span>
                        位置：{selected.spaceName}/{selected.location}
                      </span>
                      <span>
                        数量：{selected.count}
                        {selected.unit}
                      </span>
                      <span>剩余：{selected.remainingPct}%</span>
                    </div>
                  </div>
                )}

                {/* Consume options */}
                {selected && (
                  <div className="space-y-3 mb-5">
                    {/* Consume all toggle */}
                    <label className="flex items-center justify-between p-3 border-2 border-on-background rounded-xl bg-surface cursor-pointer">
                      <div className="flex items-center gap-2">
                        <Trash2 size={14} className="text-red-600" />
                        <span className="text-sm font-display font-bold text-on-background">
                          全部清除
                        </span>
                      </div>
                      <input
                        type="checkbox"
                        checked={consumeAll}
                        onChange={(e) => setConsumeAll(e.target.checked)}
                        disabled={isConfirming}
                        className="w-4 h-4 rounded border-2 border-on-background accent-primary"
                      />
                    </label>

                    {/* Partial consume count */}
                    {!consumeAll && (
                      <div className="flex items-center justify-between p-3 border-2 border-on-background rounded-xl bg-white">
                        <span className="text-sm text-on-background">消耗数量</span>
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() =>
                              setConsumeCount(Math.max(1, consumeCount - 1))
                            }
                            className="p-1 hover:bg-surface rounded-lg transition-colors"
                            disabled={isConfirming}
                          >
                            <Minus size={14} className="text-on-background" />
                          </button>
                          <span className="font-display font-extrabold text-sm w-8 text-center text-on-background">
                            {consumeCount}
                          </span>
                          <button
                            onClick={() => setConsumeCount(consumeCount + 1)}
                            className="p-1 hover:bg-surface rounded-lg transition-colors"
                            disabled={isConfirming}
                          >
                            <Plus size={14} className="text-on-background" />
                          </button>
                          <span className="text-xs text-outline ml-0.5">
                            {selected.unit}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                )}

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
                    disabled={isConfirming || !selected}
                    className="flex-1 py-3 px-4 bg-red-500 hover:bg-red-400 border-2 border-on-background rounded-full font-display font-bold text-sm text-white shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    <Check size={16} />
                    {isConfirming ? "处理中..." : "确认消耗"}
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
