import { Space, Item, Message, SystemPreferences } from './types';

export const INITIAL_SPACES: Space[] = [
  {
    id: 'kitchen',
    name: '主厨房',
    icon: 'kitchen',
    count: 42,
    warnCount: 3,
    bgClass: 'bg-primary-fixed',
    textColor: 'text-primary',
    badgeColor: 'bg-secondary-container'
  },
  {
    id: 'storage',
    name: '储藏间',
    icon: 'shelves',
    count: 128,
    warnCount: 0,
    bgClass: 'bg-tertiary-fixed',
    textColor: 'text-tertiary',
    badgeColor: 'bg-surface-container-high'
  },
  {
    id: 'garage',
    name: '车库工具',
    icon: 'garage',
    count: 15,
    warnCount: 1,
    bgClass: 'bg-secondary-fixed',
    textColor: 'text-secondary',
    badgeColor: 'bg-surface-container-high'
  }
];

export const INITIAL_ITEMS: Item[] = [
  {
    id: 'item-1',
    title: '全麦面包',
    spaceId: 'kitchen',
    spaceName: '主厨房',
    location: '厨房二级柜',
    remainingPct: 15,
    buyDate: '2026-06-01',
    expireDate: '2026-06-08',
    tag: '告急',
    count: 1,
    unit: '袋',
    icon: 'bakery_dining',
    remark: '每日早餐用，临近过期需尽快食用。'
  },
  {
    id: 'item-2',
    title: '五金工具箱',
    spaceId: 'garage',
    spaceName: '车库工具',
    location: '车库 A4 搁板',
    remainingPct: 85,
    buyDate: '2025-12-15',
    expireDate: '2029-12-15',
    tag: '充足',
    count: 8,
    unit: '件',
    icon: 'construction',
    remark: '包含螺栓螺母，完备度较高。'
  },
  {
    id: 'item-3',
    title: '便利贴',
    spaceId: 'office',
    spaceName: '储藏间', // grouped in storage tab in visual or office space
    location: '书房抽屉',
    remainingPct: 35,
    buyDate: '2026-05-10',
    expireDate: '2028-05-10',
    tag: '较低',
    count: 3,
    unit: '本',
    icon: 'edit_note',
    remark: '黄色便利贴，用于备忘。'
  },
  {
    id: 'item-4',
    title: '咖啡豆',
    spaceId: 'kitchen',
    spaceName: '主厨房',
    location: '吧台储物罐',
    remainingPct: 70,
    buyDate: '2026-05-20',
    expireDate: '2026-12-25',
    tag: '充足',
    count: 2,
    unit: '罐',
    icon: 'local_cafe',
    remark: '阿拉比卡中度烘焙，保质期长。'
  },
  {
    id: 'item-5',
    title: '洗洁精',
    spaceId: 'kitchen',
    spaceName: '主厨房',
    location: '水池下方',
    remainingPct: 50,
    buyDate: '2026-02-14',
    expireDate: '2027-02-14',
    tag: '充足',
    count: 1,
    unit: '瓶',
    icon: 'cleaning_services',
    remark: '柠檬香型，日常厨房清洁。'
  },
  {
    id: 'item-6',
    title: '常备维C',
    spaceId: 'medicine',
    spaceName: '储藏间',
    location: '药品箱 B',
    remainingPct: 20,
    buyDate: '2024-06-05',
    expireDate: '2026-06-20', // Expiring in 15 days from June 5, 2026
    tag: '过期预警',
    count: 1,
    unit: '瓶',
    icon: 'medication',
    remark: '泡腾片形式，还有约15天过期。'
  }
];

export const INITIAL_MESSAGES: Message[] = [
  {
    id: 'msg-1',
    sender: 'assistant',
    text: '嘿！我是你的松鼠管家。今天想整理点什么？你可以发照片给我，或者直接语音告诉我！🐿️',
    timestamp: '2分钟前',
    type: 'welcome'
  },
  {
    id: 'msg-2',
    sender: 'user',
    text: '[语音消息: 帮我录入刚才收到的五金工具吧]',
    timestamp: '1分钟前',
    type: 'voice',
    voiceDuration: '0:12'
  },
  {
    id: 'msg-3',
    sender: 'assistant',
    text: '收到！我已经识别出你照片里的工具。你想把它们存入 **"车库-工具箱B"** 吗？',
    timestamp: '刚刚',
    type: 'action_card',
    actionCard: {
      title: '五金工具套装',
      image: 'https://lh3.googleusercontent.com/aida-public/AB6AXuAi0e0pMmh7n9_aGTW81tBycuiOEyAZPQx9amTGNI61Tv6lVT4Cy-EJ7aNh_Jk4aJV3gAJ9c2L6_pM2Rzalf78pA3hiaojD3WUXPGNsCVyMz0RmYHmDvBTj5IYh-9d9FDeB59eiXWLIcQEsNdWQuQqYNdEwJaHhPkIjRymaNmxfiAi0EE30ZVL_HWQS5-YbunGoYMbW_0qHo_2e-l32j1TUiNFhLAEBJmGWkk3iaJlEG3fPm8vwTzK9AOaV_BXT2YvPC4IbCfyP1g5i',
      category: '车库工具',
      quantity: 8,
      spaceName: '车库工具'
    }
  }
];

export const DEFAULT_PREFERENCES: SystemPreferences = {
  allergies: ['乳制品', '麸质'],
  lifestyle: '减脂增肌中',
  warningThreshold: 5,
  lowThreshold: 15,
  reminderTime: '18:00',
  savingPath: '~/Documents/SongShuZhuChao/Library',
  aiModel: 'gemini-3.5-flash',
  temperature: 0.7,
  autoTag: true
};

export function getStoredSpaces(): Space[] {
  const data = localStorage.getItem('nest_spaces');
  if (data) {
    try {
      return JSON.parse(data);
    } catch {
      return INITIAL_SPACES;
    }
  }
  return INITIAL_SPACES;
}

export function saveStoredSpaces(spaces: Space[]) {
  localStorage.setItem('nest_spaces', JSON.stringify(spaces));
}

export function getStoredItems(): Item[] {
  const data = localStorage.getItem('nest_items');
  if (data) {
    try {
      return JSON.parse(data);
    } catch {
      return INITIAL_ITEMS;
    }
  }
  return INITIAL_ITEMS;
}

export function saveStoredItems(items: Item[]) {
  localStorage.setItem('nest_items', JSON.stringify(items));
}

export function getStoredMessages(): Message[] {
  const data = localStorage.getItem('nest_messages');
  if (data) {
    try {
      return JSON.parse(data);
    } catch {
      return INITIAL_MESSAGES;
    }
  }
  return INITIAL_MESSAGES;
}

export function saveStoredMessages(messages: Message[]) {
  localStorage.setItem('nest_messages', JSON.stringify(messages));
}

export function getStoredPreferences(): SystemPreferences {
  const data = localStorage.getItem('nest_preferences');
  if (data) {
    try {
      return JSON.parse(data);
    } catch {
      return DEFAULT_PREFERENCES;
    }
  }
  return DEFAULT_PREFERENCES;
}

export function saveStoredPreferences(preferences: SystemPreferences) {
  localStorage.setItem('nest_preferences', JSON.stringify(preferences));
}

export function getOnboardingDone(): boolean {
  return localStorage.getItem('nest_onboarding_done') === 'true';
}

export function setOnboardingDone(done: boolean) {
  localStorage.setItem('nest_onboarding_done', done ? 'true' : 'false');
}
