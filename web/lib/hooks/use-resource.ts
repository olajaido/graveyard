'use client';
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/lib/api/client';
import { cacheGet, cacheSet } from '@/lib/api/cache';

export type Resource<T> =
  { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; error: ApiError };

type Settled<T> = { id: string; result: Exclude<Resource<T>, { status: 'loading' }> };

/**
 * Loads one thing from the API. `key` null means "not yet" (the query has not been read yet). A value that passes
 * `cacheable` is kept for the session, so going back to a finished scan does not fetch it again. State is set only
 * when an answer arrives; "loading" is derived from the key, so no effect sets state synchronously.
 */
export function useResource<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
  cacheable: (value: T) => boolean = () => false,
): Resource<T> & { reload: () => void } {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const id = key === null ? null : `${key}#${attempt}`;
  const hit = key !== null && attempt === 0 ? cacheGet<T>(key) : undefined;

  useEffect(() => {
    if (key === null || id === null || hit !== undefined) return;
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => {
        if (controller.signal.aborted) return;
        if (cacheable(data)) cacheSet(key, data);
        setSettled({ id, result: { status: 'ready', data } });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError = error instanceof ApiError ? error : new ApiError('network');
        setSettled({ id, result: { status: 'error', error: apiError } });
      },
    );
    return () => controller.abort();
    // `load` and `cacheable` are new functions on every render; the key says what is loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, id, hit]);

  if (hit !== undefined) return { status: 'ready', data: hit, reload };
  if (settled && settled.id === id) return { ...settled.result, reload };
  return { status: 'loading', reload };
}
