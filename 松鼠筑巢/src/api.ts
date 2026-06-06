import { Item, Message, Space, SystemPreferences } from './types';

export interface AppState {
  onboardingDone: boolean;
  spaces: Space[];
  items: Item[];
  messages: Message[];
  preferences: SystemPreferences;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers || {})
    }
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function fetchState(): Promise<AppState> {
  return request<AppState>('/api/state');
}

export function saveState(partial: Partial<AppState>): Promise<AppState> {
  return request<AppState>('/api/state', {
    method: 'PUT',
    body: JSON.stringify(partial)
  });
}

export function createItem(item: Partial<Item>): Promise<Item> {
  return request<Item>('/api/items', {
    method: 'POST',
    body: JSON.stringify(item)
  });
}

export function updateItem(id: string, item: Partial<Item>): Promise<Item> {
  return request<Item>(`/api/items/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(item)
  });
}

export function deleteItem(id: string): Promise<{ ok: true }> {
  return request<{ ok: true }>(`/api/items/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });
}

export function exportMarkdown(): Promise<{ ok: true; path: string }> {
  return request<{ ok: true; path: string }>('/api/export?format=md', {
    method: 'POST'
  });
}
