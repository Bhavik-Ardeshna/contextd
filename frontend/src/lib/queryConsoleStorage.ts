export type QueryRecipe = 'rrf' | 'graph-chat';

export interface QueryHistoryItem {
  id: string;
  query: string;
  databaseId: string;
  databaseName: string;
  createdAt: string;
  latencyMs: number;
  resultCount: number;
  recipe?: QueryRecipe;
}

export interface SavedQuery {
  id: string;
  title: string;
  query: string;
  databaseId: string;
  databaseName?: string;
  createdAt: string;
  updatedAt?: string;
  recipe?: QueryRecipe;
  lastRunAt?: string;
  latencyMs?: number | null;
  resultCount?: number | null;
  rating?: number | null;
}

export const QUERY_HISTORY_KEY = 'contextd.queryConsole.history';
export const SAVED_QUERIES_KEY = 'contextd.queryConsole.saved';
export const SAVED_QUERIES_EVENT = 'contextd:saved-queries-updated';

function readLocalArray<T>(key: string): T[] {
  if (typeof window === 'undefined') return [];
  try {
    const value = window.localStorage.getItem(key);
    return value ? (JSON.parse(value) as T[]) : [];
  } catch {
    return [];
  }
}

function writeLocalArray<T>(key: string, value: T[]) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

function notifySavedQueriesChanged() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(SAVED_QUERIES_EVENT));
}

export function readQueryHistory() {
  return readLocalArray<QueryHistoryItem>(QUERY_HISTORY_KEY);
}

export function writeQueryHistory(value: QueryHistoryItem[]) {
  writeLocalArray(QUERY_HISTORY_KEY, value);
}

export function readSavedQueries() {
  return readLocalArray<SavedQuery>(SAVED_QUERIES_KEY);
}

export function writeSavedQueries(value: SavedQuery[]) {
  writeLocalArray(SAVED_QUERIES_KEY, value);
  notifySavedQueriesChanged();
}

export function queryConsoleUrl(item: Pick<SavedQuery, 'databaseId' | 'query' | 'recipe'>) {
  const params = new URLSearchParams();
  if (item.databaseId) params.set('database', item.databaseId);
  params.set('q', item.query);
  params.set('recipe', item.recipe || 'rrf');
  return `/query?${params.toString()}`;
}
