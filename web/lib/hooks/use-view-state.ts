'use client';
import { useCallback, useSyncExternalStore } from 'react';
import { parseViewState, viewStateSearch, type View, type ViewState } from '@/lib/model/route';
import { useQueryString } from './use-query-state';

export const VIEW_STORAGE_KEY = 'graveyard.view';
const STORAGE_EVENT = 'gy:viewpreference';

function subscribeStorage(onChange: () => void): () => void {
  window.addEventListener('storage', onChange);
  window.addEventListener(STORAGE_EVENT, onChange);
  return () => {
    window.removeEventListener('storage', onChange);
    window.removeEventListener(STORAGE_EVENT, onChange);
  };
}

function readStoredView(): View | null {
  try {
    const value = window.localStorage.getItem(VIEW_STORAGE_KEY);
    return value === 'scene' || value === 'table' ? value : null;
  } catch {
    return null; // storage can be blocked
  }
}

/**
 * The view state of the scan page (ui-core UI-GY-8, UI-GY-10). The query string is the source of truth, so a link shows
 * the same screen. The chosen view is also remembered in this browser; the URL wins, and the remembered choice is only
 * used when the URL has none.
 */
export function useViewState(): {
  state: ViewState & { view: View };
  update: (change: Partial<ViewState>) => void;
} {
  const [search, setSearch] = useQueryString();
  const stored = useSyncExternalStore<View | null>(subscribeStorage, readStoredView, () => null);
  const params = new URLSearchParams(search ?? '');
  const parsed = parseViewState(params);
  const state = { ...parsed, view: parsed.view ?? stored ?? 'scene' };

  const update = useCallback(
    (change: Partial<ViewState>) => {
      const current = new URLSearchParams(window.location.search);
      const next = { ...parseViewState(current), ...change };
      if ('view' in change && change.view) {
        try {
          window.localStorage.setItem(VIEW_STORAGE_KEY, change.view);
          window.dispatchEvent(new Event(STORAGE_EVENT));
        } catch {
          // The choice is still in the URL.
        }
      }
      setSearch(viewStateSearch(next, current));
    },
    [setSearch],
  );
  return { state, update };
}
