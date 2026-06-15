import React, { useState, useEffect } from "react";
import { InventoryItem, InventoryCategory } from "../types";
import { CATEGORY_MAP } from "../utils";
import { motion, AnimatePresence } from "motion/react";
import { X, Save, Trash, Calendar, Plus, Bookmark, HelpCircle } from "lucide-react";
import { Modal } from "./Modal";

interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  action: 'create' | 'edit' | 'view';
  item: InventoryItem | null;
  locations: string[];
  onSave: (item: InventoryItem) => Promise<void> | void;
  onDelete: (id: string) => Promise<void> | void;
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  action,
  item,
  locations,
  onSave,
  onDelete,
}) => {
  const [name, setName] = useState("");
  const [category, setCategory] = useState<InventoryCategory>("food");
  const [quantity, setQuantity] = useState(1);
  const [unit, setUnit] = useState("个");
  const [location, setLocation] = useState("");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [hasExpiry, setHasExpiry] = useState(true);
  const [expiryDate, setExpiryDate] = useState("");
  const [remindDays, setRemindDays] = useState(5);
  const [tags, setTags] = useState<string[]>([]);
  const [newTag, setNewTag] = useState("");
  const [note, setNote] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [alertModal, setAlertModal] = useState<{
    isOpen: boolean;
    message: string;
  }>({ isOpen: false, message: "" });

  const [deleteConfirmModal, setDeleteConfirmModal] = useState<{
    isOpen: boolean;
    itemId: string;
    itemName: string;
  }>({ isOpen: false, itemId: "", itemName: "" });

  const defaultLocations = locations.length > 0 ? locations : ["主冰箱", "厨房储物柜", "玄关柜"];

  // Populate data when item or action changes
  useEffect(() => {
    if (isOpen) {
      if (item && (action === "edit" || action === "view")) {
        setName(item.name);
        setCategory(item.category);
        setQuantity(item.quantity);
        setUnit(item.unit || "个");
        setLocation(item.location);
        setPurchaseDate(item.purchaseDate || new Date().toISOString().split("T")[0]);
        if (item.expiryDate) {
          setHasExpiry(true);
          setExpiryDate(item.expiryDate);
        } else {
          setHasExpiry(false);
          setExpiryDate("");
        }
        setRemindDays(item.remindDaysBefore ?? 5);
        setTags(item.tags || []);
        setNote(item.note || "");
      } else {
        // Create mode
        setName("");
        setCategory("food");
        setQuantity(1);
        setUnit("个");
        setLocation(defaultLocations[0]);
        setPurchaseDate(new Date().toISOString().split("T")[0]);
        setHasExpiry(true);
        setExpiryDate(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split("T")[0]); // 7 days from now
        setRemindDays(5);
        setTags([]);
        setNote("");
      }
    }
  }, [isOpen, item, action]);

  const handleAddTag = (e: React.FormEvent) => {
    e.preventDefault();
    if (newTag.trim() && !tags.includes(newTag.trim())) {
      setTags([...tags, newTag.trim()]);
      setNewTag("");
    }
  };

  const handleRemoveTag = (t: string) => {
    setTags(tags.filter(tag => tag !== t));
  };

  const handleSave = async () => {
    if (!name.trim()) {
      setAlertModal({
        isOpen: true,
        message: "吱！请写上物体的名字，不然松鼠记不住呀！",
      });
      return;
    }

    const payload: InventoryItem = {
      id: item?.id || "item-" + Date.now(),
      name: name.trim(),
      category,
      quantity: Number(quantity) || 1,
      unit: unit.trim() || "个",
      location,
      purchaseDate,
      expiryDate: hasExpiry && expiryDate ? expiryDate : undefined,
      remindDaysBefore: remindDays,
      tags,
      note: note.trim()
    };

    setIsSaving(true);
    setSaveError(null);

    try {
      await onSave(payload);
      onClose();
    } catch (error) {
      console.error("Failed to save inventory item", error);
      setSaveError("保存失败，请确认后端服务已启动后重试。");
    } finally {
      setIsSaving(false);
    }
  };

  const isView = action === "view";

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.5 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black z-40 cursor-pointer"
          />

          {/* Drawer main layer */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="fixed top-0 right-0 h-full w-full max-w-lg bg-background border-l-4 border-on-background z-50 shadow-2xl flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="p-5 border-b-2 border-on-background bg-primary-fixed flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-2xl">🐿️</span>
                <div>
                  <h3 className="font-display font-bold text-on-background text-[17px]">
                    {action === "create" ? "新增小窝库存" : isView ? "看一眼松枝藏品" : "改写藏品档案"}
                  </h3>
                  <p className="text-[11px] text-outline font-sans">
                    {action === "create" ? "松鼠已准备好挖树洞屯粮啦" : `档案编码: ${item?.id || "N/A"}`}
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 border-2 border-on-background rounded-full hover:bg-surface active-press-sm cursor-pointer"
              >
                <X size={18} className="text-on-background" />
              </button>
            </div>

            {/* Scrollable form */}
            <div className="flex-1 overflow-y-auto p-5 space-y-5 bg-paper scrollbar-hide">
              {/* Name */}
              <div className="space-y-1.5">
                <label className="text-xs font-bold text-on-background block">物品名称 <span className="text-primary">*</span></label>
                <input
                  type="text"
                  placeholder="如：松子罐、布洛芬、数据线"
                  disabled={isView}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full p-2.5 border-2 border-on-background rounded-xl bg-white text-sm focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-75 disabled:bg-surface-container"
                />
              </div>

              {/* Category & Location */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-on-background block">归口分类</label>
                  <select
                    disabled={isView}
                    value={category}
                    onChange={(e) => setCategory(e.target.value as InventoryCategory)}
                    className="w-full p-2.5 border-2 border-on-background rounded-xl bg-white text-sm focus:outline-none focus:ring-1 focus:ring-primary relative z-10 cursor-pointer disabled:cursor-not-allowed disabled:opacity-75 disabled:bg-surface-container"
                  >
                    {Object.entries(CATEGORY_MAP).map(([key, meta]) => (
                      <option key={key} value={key}>
                        {meta.chineseName}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-on-background block">储藏树桠角落</label>
                  <select
                    disabled={isView}
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                    className="w-full p-2.5 border-2 border-on-background rounded-xl bg-white text-sm focus:outline-none focus:ring-1 focus:ring-primary relative z-10 cursor-pointer disabled:cursor-not-allowed disabled:opacity-75 disabled:bg-surface-container"
                  >
                    {defaultLocations.map((loc) => (
                      <option key={loc} value={loc}>
                        {loc}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Quantity & Unit */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-on-background block">储藏数量</label>
                  <div className="flex items-center border-2 border-on-background rounded-xl bg-white overflow-hidden">
                    <button
                      type="button"
                      disabled={isView || quantity <= 1}
                      onClick={() => setQuantity(Math.max(1, quantity - 1))}
                      className="px-3 py-1 bg-surface-container border-r-2 border-on-background font-bold text-on-background disabled:opacity-50 cursor-pointer text-sm"
                    >
                      -
                    </button>
                    <input
                      type="number"
                      disabled={isView}
                      value={quantity}
                      onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-full text-center p-1 bg-transparent border-0 text-sm focus:outline-none"
                    />
                    <button
                      type="button"
                      disabled={isView}
                      onClick={() => setQuantity(quantity + 1)}
                      className="px-3 py-1 bg-surface-container border-l-2 border-on-background font-bold text-on-background cursor-pointer text-sm"
                    >
                      +
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-on-background block">数量单位</label>
                  <input
                    type="text"
                    disabled={isView}
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                    placeholder="例如: 个, 瓶, 盒"
                    className="w-full p-2.5 border-2 border-on-background rounded-xl bg-white text-sm focus:outline-none"
                  />
                </div>
              </div>

              {/* Expiry Switch */}
              <div className="p-3.5 border-2 border-on-background bg-surface-container-high rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-xs font-bold text-on-background block">保质期与消耗预警</span>
                    <span className="text-[10px] text-outline">电子产品或杂物可关闭此开关</span>
                  </div>
                  <input
                    type="checkbox"
                    disabled={isView}
                    checked={hasExpiry}
                    onChange={(e) => setHasExpiry(e.target.checked)}
                    className="w-4 h-4 rounded border-2 border-on-background accent-primary "
                  />
                </div>

                {hasExpiry && (
                  <div className="space-y-3 pt-2.5 border-t border-outline-variant">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-[11px] text-outline block mb-1">采购筑巢日期</label>
                        <input
                          type="date"
                          disabled={isView}
                          value={purchaseDate}
                          onChange={(e) => setPurchaseDate(e.target.value)}
                          className="w-full p-2 border-2 border-on-background rounded-lg bg-white text-xs relative z-10 cursor-pointer disabled:cursor-not-allowed disabled:opacity-75 disabled:bg-surface-container"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] text-outline block mb-1">保质期至 (底线)</label>
                        <input
                          type="date"
                          disabled={isView}
                          value={expiryDate}
                          onChange={(e) => setExpiryDate(e.target.value)}
                          className="w-full p-2 border-2 border-on-background rounded-lg bg-white text-xs border-dashed relative z-10 cursor-pointer disabled:cursor-not-allowed disabled:opacity-75 disabled:bg-surface-container"
                        />
                      </div>
                    </div>

                    <div>
                      <div className="flex items-center justify-between text-[11px] text-outline mb-1">
                        <span>提早预警时间线: 提早天数</span>
                        <span className="font-bold text-on-background">{remindDays} 天</span>
                      </div>
                      <input
                        type="range"
                        min="1"
                        max="30"
                        disabled={isView}
                        value={remindDays}
                        onChange={(e) => setRemindDays(Number(e.target.value))}
                        className="w-full accent-primary bg-surface-container relative z-10 cursor-pointer disabled:cursor-not-allowed"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Tags block */}
              <div className="space-y-1.5">
                <label className="text-xs font-bold text-on-background block flex items-center gap-1">
                  <Bookmark size={14} className="text-secondary" /> 贴纸标签 (点击标签可以移除)
                </label>
                <div className="flex flex-wrap gap-1.5 p-2 border-2 border-on-background bg-white rounded-xl min-h-[44px]">
                  {tags.map((t) => (
                    <button
                      key={t}
                      type="button"
                      disabled={isView}
                      onClick={() => handleRemoveTag(t)}
                      className="px-2 py-1 text-xs font-medium bg-secondary-container text-on-secondary-container border-2 border-on-background rounded-md flex items-center gap-1 active-press"
                    >
                      #{t} {!isView && <span className="text-[9px]">×</span>}
                    </button>
                  ))}
                  {tags.length === 0 && <span className="text-xs text-outline italic self-center">无贴纸...</span>}
                </div>
                {!isView && (
                  <form onSubmit={handleAddTag} className="flex gap-2">
                    <input
                      type="text"
                      placeholder="快输入新标签添加..."
                      value={newTag}
                      onChange={(e) => setNewTag(e.target.value)}
                      className="flex-1 p-2 border-2 border-on-background rounded-lg bg-white text-xs focus:outline-none"
                    />
                    <button
                      type="submit"
                      className="px-3.5 py-1.5 bg-secondary text-white text-xs border-2 border-on-background rounded-lg hover:bg-opacity-90 active-press cursor-pointer flex items-center gap-1"
                    >
                      <Plus size={12} /> 添加
                    </button>
                  </form>
                )}
              </div>

              {/* Notes */}
              <div className="space-y-1.5">
                <label className="text-xs font-bold text-on-background block">松鼠备忘录</label>
                <textarea
                  disabled={isView}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="写点松鼠提示，比如‘吃了半盒，剩下的开封了记得早点吃吱！’"
                  rows={3}
                  className="w-full p-2.5 border-2 border-on-background rounded-xl bg-white text-sm focus:outline-none disabled:opacity-75 disabled:bg-surface-container"
                />
              </div>
            </div>

            {saveError && (
              <div className="border-t-2 border-on-background bg-red-50 px-4 py-3 text-xs font-bold text-red-600">
                {saveError}
              </div>
            )}

            {/* Sticky Actions in footer */}
            <div className="p-4 border-t-2 border-on-background bg-surface-container flex items-center justify-between gap-3">
              {item && !isView && (
                <button
                  disabled={isSaving}
                  onClick={() => {
                    setDeleteConfirmModal({
                      isOpen: true,
                      itemId: item.id,
                      itemName: item.name,
                    });
                  }}
                  className="flex items-center gap-1.5 bg-error text-white font-display border-2 border-on-background hover:bg-opacity-95 px-4 py-2 text-xs rounded-xl active-press cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Trash size={14} />
                  销毁此档案
                </button>
              )}

              {isView && item && (
                <button
                  onClick={() => {
                    // Turn to edit
                    // Yes, we edit inside the outer state
                    onSave({ ...item, id: item.id });
                    onClose();
                  }}
                  className="w-full flex items-center justify-center gap-1.5 bg-[#91f78e] font-display border-2 border-on-background px-4 py-2.5 text-xs rounded-xl active-press cursor-pointer font-bold text-on-background"
                >
                  立刻改写这份档案
                </button>
              )}

              {!(isView) && (
                <div className="flex-1 flex justify-end gap-2">
                  <button
                    onClick={onClose}
                    className="px-4 py-2 border-2 border-on-background bg-white text-on-background font-display text-xs rounded-xl hover:bg-surface hover:border-black cursor-pointer"
                  >
                    放弃改动
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={isSaving}
                    className="flex items-center gap-1 bg-primary text-white font-display border-2 border-on-background hover:bg-opacity-95 px-5 py-2 text-xs rounded-xl active-press cursor-pointer hard-shadow-sm font-bold disabled:cursor-not-allowed disabled:opacity-60 disabled:translate-x-0 disabled:translate-y-0"
                  >
                    <Save size={14} />
                    {isSaving ? "正在封存..." : "封存并归巢"}
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}

      {/* Modals */}
      <Modal
        isOpen={alertModal.isOpen}
        onClose={() => setAlertModal({ isOpen: false, message: "" })}
        type="alert"
        variant="warning"
        message={alertModal.message}
      />

      <Modal
        isOpen={deleteConfirmModal.isOpen}
        onClose={() => setDeleteConfirmModal({ isOpen: false, itemId: "", itemName: "" })}
        onConfirm={async () => {
          setIsSaving(true);
          setSaveError(null);
          try {
            await onDelete(deleteConfirmModal.itemId);
            onClose();
          } catch (error) {
            console.error("Failed to delete inventory item", error);
            setSaveError("删除失败，请确认后端服务已启动后重试。");
          } finally {
            setIsSaving(false);
          }
        }}
        type="confirm"
        variant="danger"
        title="确认销毁"
        message={`吱！您确定要摧毁【${deleteConfirmModal.itemName}】的档案，把它从树洞里腾出来吗？`}
        confirmText="确认销毁"
        cancelText="再想想"
      />
    </AnimatePresence>
  );
};
