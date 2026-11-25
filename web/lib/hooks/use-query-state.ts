'use client';
import { useCallback, useSyncExternalStore } from 'react';

const EVENT = 'gy:locationchange';

function subscribe(onChange: () => void): () => void {
  window.addEventListener('popstate', onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener('popstate', onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

const clientSnapshot = (): string => window.location.search;
// The exported HTML is the same for every link, so the server has no query: pages show their loading state until
// the browser has read it (design 3). `null` means "not read yet".
const serverSnapshot = (): string | null => null;

/**
 * The query string of the current page, or `null` before the browser has read it, and a setter that replaces it
 * without a navigation (the view state of the scan page lives there). It reads the URL through
 * `useSyncExternalStore`, not `useSearchParams`, because a static export needs a Suspense boundary for that hook.
 */
export function useQueryString(): readonly [string | null, (params: URLSearchParams) => void] {
  const search = useSyncExternalStore<string | null>(subscribe, clientSnapshot, serverSnapshot);
  const set = useCallback((params: URLSearchParams) => {
    const query = params.toString();
    const url = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`;
    window.history.replaceState(window.history.state, '', url);
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [search, set] as const;
}
