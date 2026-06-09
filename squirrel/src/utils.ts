import { InventoryItem, InventoryCategory } from "./types";

// Pre-populated default items representing a warm "Squirrel's Nest" setup
export const DEFAULT_INVENTORY_ITEMS: InventoryItem[] = [
  {
    id: "item-1",
    name: "有机野生原味松子",
    category: "food",
    quantity: 3,
    unit: "罐",
    location: "厨房储物柜",
    purchaseDate: "2026-06-01",
    expiryDate: "2026-09-01",
    remindDaysBefore: 10,
    tags: ["坚果", "小零食", "最爱"],
    note: "松鼠最爱的松子！每天吃一小把可以补充优质油脂和维生素吱。"
  },
  {
    id: "item-2",
    name: "低温巴氏鲜牛奶",
    category: "food",
    quantity: 1,
    unit: "大瓶",
    location: "主冰箱",
    purchaseDate: "2026-06-04",
    // To keep it dynamic, let's make it expire in 3 days from "now"
    expiryDate: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    remindDaysBefore: 5,
    tags: ["乳制品", "早餐"],
    note: "保质期极短！记得每天早上配燕麦片喝完，冷藏保存吱。"
  },
  {
    id: "item-3",
    name: "法式黄油羊角面包",
    category: "food",
    quantity: 4,
    unit: "个",
    location: "厨房储物柜",
    purchaseDate: "2026-06-05",
    // Expired item for illustration
    expiryDate: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
    remindDaysBefore: 2,
    tags: ["面包", "主食"],
    note: "哎呀呀，本松检查到这个面包昨天就已经到期了！快闻一闻有没有坏吱！"
  },
  {
    id: "item-4",
    name: "布洛芬缓释胶囊",
    category: "medicine",
    quantity: 12,
    unit: "粒",
    location: "玄关柜",
    purchaseDate: "2026-05-10",
    expiryDate: "2027-05-10",
    remindDaysBefore: 15,
    tags: ["常备药", "止痛", "发烧"],
    note: "小药箱储备，发热或头痛时遵医嘱服用吱。"
  },
  {
    id: "item-5",
    name: "防水防尘创可贴",
    category: "medicine",
    quantity: 1,
    unit: "盒",
    location: "玄关柜",
    purchaseDate: "2026-05-01",
    expiryDate: "2029-05-01",
    remindDaysBefore: 30,
    tags: ["日常防护", "急救"],
    note: "玄关一进门的小箱子里，做家务不小心划破手时赶紧贴一个吱。"
  },
  {
    id: "item-6",
    name: "无源有线机械键盘",
    category: "electronics",
    quantity: 1,
    unit: "把",
    location: "书房储蓄阁",
    purchaseDate: "2026-03-15",
    remindDaysBefore: 0,
    tags: ["外设", "办公"],
    note: "青轴机械键盘，敲击声音极其悦耳。放书房保持干燥防尘吱。"
  },
  {
    id: "item-7",
    name: "特浓舒缓玻尿酸面膜",
    category: "cosmetics",
    quantity: 8,
    unit: "片",
    location: "玄关柜",
    purchaseDate: "2026-05-20",
    expiryDate: "2026-11-20",
    remindDaysBefore: 15,
    tags: ["护肤", "补水"],
    note: "晚上洗完脸贴一片。注意避光，不要跟热水管放一起吱。"
  }
];

// Calculate item countdown days and status
export interface ItemStatusInfo {
  status: 'fresh' | 'warning' | 'expired' | 'permanent';
  daysLeft: number;
  displayText: string;
}

export function getItemStatus(item: InventoryItem, strategy: 'normal' | 'strict' | 'relaxed'): ItemStatusInfo {
  if (!item.expiryDate) {
    return { status: 'permanent', daysLeft: 9999, displayText: '永久保质' };
  }

  const todayStr = new Date().toISOString().split("T")[0];
  const today = new Date(todayStr).getTime();
  const expiry = new Date(item.expiryDate).getTime();
  
  const diffTime = expiry - today;
  const daysLeft = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
  
  // Expiration settings multiplier
  let threshold = item.remindDaysBefore;
  if (strategy === 'strict') {
    threshold = Math.max(threshold, 10); // alert 10 days before minimum
  } else if (strategy === 'relaxed') {
    threshold = Math.min(threshold, 2); // alert at most 2 days before
  }

  if (daysLeft < 0) {
    return {
      status: 'expired',
      daysLeft,
      displayText: `已过期 ${Math.abs(daysLeft)} 天`
    };
  } else if (daysLeft <= threshold) {
    return {
      status: 'warning',
      daysLeft,
      displayText: daysLeft === 0 ? "今天到期！" : `仅剩 ${daysLeft} 天`
    };
  } else {
    return {
      status: 'fresh',
      daysLeft,
      displayText: `还剩 ${daysLeft} 天`
    };
  }
}

// Map categories to user-friendly Chinese names & colors
export interface CategoryMeta {
  chineseName: string;
  bgColor: string;
  textColor: string;
  borderColor: string;
}

export const CATEGORY_MAP: Record<InventoryCategory, CategoryMeta> = {
  food: {
    chineseName: "食材美食",
    bgColor: "bg-amber-100",
    textColor: "text-amber-900",
    borderColor: "border-amber-400"
  },
  medicine: {
    chineseName: "健康药箱",
    bgColor: "bg-red-100",
    textColor: "text-red-900",
    borderColor: "border-red-400"
  },
  electronics: {
    chineseName: "电器外设",
    bgColor: "bg-blue-100",
    textColor: "text-blue-900",
    borderColor: "border-blue-400"
  },
  cosmetics: {
    chineseName: "面容护理",
    bgColor: "bg-pink-100",
    textColor: "text-pink-900",
    borderColor: "border-pink-400"
  },
  book: {
    chineseName: "林间书阁",
    bgColor: "bg-emerald-100",
    textColor: "text-emerald-900",
    borderColor: "border-emerald-400"
  },
  other: {
    chineseName: "金秋杂物",
    bgColor: "bg-orange-100",
    textColor: "text-orange-900",
    borderColor: "border-orange-400"
  }
};
