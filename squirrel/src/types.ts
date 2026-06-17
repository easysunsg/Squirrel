export type InventoryCategory = 'food' | 'medicine' | 'electronics' | 'cosmetics' | 'book' | 'other';

export interface InventoryItem {
  id: string;
  name: string;
  category: InventoryCategory;
  quantity: number;
  unit: string;
  location: string;
  purchaseDate: string;
  expiryDate?: string; // YYYY-MM-DD
  remindDaysBefore: number;
  tags: string[];
  note: string;
}

export type SquirrelPersonality = 'humorous' | 'gabby' | 'gentle' | 'strict_squirrel';

export interface PendingItem {
  title: string;
  count: number;
  unit: string;
  category: InventoryCategory;
  location: string;
  spaceName?: string;
  expireDate?: string;
  remark?: string;
}

export interface AppSettings {
  onboardingComplete: boolean;
  selectedLocations: string[];
  dietaryHabits: string[];
  lifestyleTag: string;
  reminderTime: string;
  expirationStrategy: 'normal' | 'strict' | 'relaxed';
  squirrelPersonality: SquirrelPersonality;
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  itemSuggestion?: {
    pendingId?: string;
    items?: PendingItem[];
    matches?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
}

export interface ChatApiResponse {
  reply?: string;
  itemSuggestion?: {
    pendingId?: string;
    items?: PendingItem[];
    matches?: Array<Record<string, unknown>>;
  };
  messages?: ChatMessage[];
  items?: unknown[];
  needsConfirmation?: boolean;
  pendingId?: string;
}

export type DrawerActionType = 'view' | 'edit' | 'create';
