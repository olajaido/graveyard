/**
 * A per-session cache of API answers (ui-core UI-API-6). Only a finished scan and its graves are stored: a scan that is
 * still running changes and is never cached. The map is cleared on a reload because it lives in memory.
 */
const store = new Map<string, unknown>();

export function cacheGet<T>(key: string): T | undefined {
  return store.get(key) as T | undefined;
}

export function cacheSet(key: string, value: unknown): void {
  store.set(key, value);
}

export function clearCache(): void {
  store.clear();
}
