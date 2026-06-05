export interface Space {
  id: string;
  name: string;
  icon: string;
  count: number;
  warnCount: number;
  bgClass: string;
  textColor: string;
  badgeColor: string;
}

export interface Item {
  id: string;
  title: string;
  spaceId: string;
  spaceName: string;
  location: string;
  remainingPct: number; // 0 - 100
  buyDate: string;
  expireDate: string;
  tag: '告急' | '较低' | '充足' | '过期预警';
  count: number;
  unit: string;
  remark?: string;
  icon: string;
}

export interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  type: 'text' | 'voice' | 'action_card' | 'welcome';
  voiceDuration?: string;
  actionCard?: {
    title: string;
    image: string;
    category: string;
    quantity: number;
    spaceName: string;
    itemDetails?: any;
  };
}

export interface SystemPreferences {
  allergies: string[];
  lifestyle: string;
  warningThreshold: number; // e.g. 5
  lowThreshold: number; // e.g. 15
  reminderTime: string; // e.g. "18:00"
  savingPath: string; // e.g. "~/Documents/SongShuZhuChao/Library"
  aiModel: string; // e.g. "gemini-3.5-flash"
  temperature: number; // e.g. 0.7
  autoTag: boolean;
}
