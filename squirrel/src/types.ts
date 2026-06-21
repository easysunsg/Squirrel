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
    consumeAll?: boolean;
  };
  messages?: ChatMessage[];
  items?: unknown[];
  needsConfirmation?: boolean;
  pendingId?: string;
}

export type DrawerActionType = 'view' | 'edit' | 'create';

export interface ConsumeCandidate {
  id?: string;
  title: string;
  spaceName: string;
  location: string;
  count: number;
  unit: string;
  remainingPct: number;
}

export interface ConsumeConfirmState {
  pendingId: string;
  candidates: ConsumeCandidate[];
  consumeAll: boolean;
  replyText: string;
}

export interface RecipeCard {
  recipe_name: string;
  core_expiring_food: string[];
  other_ingredients: string[];
  cooking_steps: string[];
  estimated_time: string;
  difficulty: string;
  waste_tip: string;
}

export interface RecipeRecommend {
  title: string;
  subtitle: string;
  intro: string;
  recipe_list: RecipeCard[];
  summary_tip: string;
}
