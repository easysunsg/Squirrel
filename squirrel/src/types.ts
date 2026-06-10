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
  itemSuggestion?: Partial<InventoryItem>; // AI returned recognition suggestions
}

export interface ChatApiResponse {
  reply?: string;
  itemSuggestion?: Partial<InventoryItem>;
  messages?: ChatMessage[];
  items?: unknown[];
}

export type DrawerActionType = 'view' | 'edit' | 'create';
