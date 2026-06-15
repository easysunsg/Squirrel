import React from "react";
import { motion, AnimatePresence } from "motion/react";
import { AlertTriangle, Info, X } from "lucide-react";

export type ModalType = "confirm" | "alert";
export type ModalVariant = "warning" | "danger" | "info";

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm?: () => void;
  type?: ModalType;
  variant?: ModalVariant;
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  type = "alert",
  variant = "info",
  title,
  message,
  confirmText = "确认",
  cancelText = "取消",
}) => {
  const handleConfirm = () => {
    onConfirm?.();
    onClose();
  };

  const variantStyles = {
    warning: {
      bg: "bg-[#ffe92e]",
      border: "border-[#8f7a00]",
      iconBg: "bg-[#fff27a]",
      iconColor: "text-[#665800]",
      icon: AlertTriangle,
    },
    danger: {
      bg: "bg-[#ffd5d1]",
      border: "border-red-500",
      iconBg: "bg-[#ffe9e6]",
      iconColor: "text-red-600",
      icon: AlertTriangle,
    },
    info: {
      bg: "bg-white",
      border: "border-primary",
      iconBg: "bg-[#98f28d]",
      iconColor: "text-primary",
      icon: Info,
    },
  };

  const style = variantStyles[variant];
  const Icon = style.icon;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-transparent z-[9998]"
            onClick={onClose}
          />

          {/* Modal */}
          <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 pointer-events-none">
            <motion.div
              initial={{ scale: 0.9, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.9, opacity: 0, y: 20 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              className="pointer-events-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div
                className={`${style.bg} border-[3px] ${style.border} shadow-[8px_10px_0_0_#1b1c1c] rounded-[32px] p-6 max-w-md w-full relative`}
              >
                {/* Close button */}
                <button
                  onClick={onClose}
                  className="absolute top-4 right-4 p-1.5 hover:bg-black hover:bg-opacity-10 rounded-full transition-colors"
                  aria-label="关闭"
                >
                  <X size={18} className="text-on-background" />
                </button>

                {/* Content */}
                <div className="flex flex-col items-center text-center space-y-4">
                  {/* Icon */}
                  <div
                    className={`p-4 ${style.iconBg} rounded-full border-2 border-on-background`}
                  >
                    <Icon className={`${style.iconColor} stroke-[2.5]`} size={32} />
                  </div>

                  {/* Title */}
                  {title && (
                    <h3 className="font-display font-extrabold text-lg text-on-background">
                      {title}
                    </h3>
                  )}

                  {/* Message */}
                  <p className="text-sm text-on-background leading-relaxed px-2">
                    {message}
                  </p>

                  {/* Actions */}
                  <div className="flex gap-3 w-full pt-2">
                    {type === "confirm" ? (
                      <>
                        <button
                          onClick={onClose}
                          className="flex-1 py-3 px-4 bg-[#ece7e8] hover:bg-white border-2 border-on-background rounded-full font-display font-bold text-sm text-on-background shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer"
                        >
                          {cancelText}
                        </button>
                        <button
                          onClick={handleConfirm}
                          className="flex-1 py-3 px-4 bg-primary hover:bg-primary-container border-2 border-on-background rounded-full font-display font-bold text-sm text-white shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer"
                        >
                          {confirmText}
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={onClose}
                        className="w-full py-3 px-4 bg-primary hover:bg-primary-container border-2 border-on-background rounded-full font-display font-bold text-sm text-white shadow-[2px_3px_0_0_#1b1c1c] active-press cursor-pointer"
                      >
                        知道了
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
};
