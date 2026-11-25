'use client';
import { useCallback, useEffect, useState } from 'react';
import { cacheGet, cacheSet } from '@/lib/api/cache';
import { ApiError, type Client } from '@/lib/api/client';
import { getClient } from '@/lib/api/config';
import type { Scan } from '@/lib/api/types';
import { FIRST_DELAY_MS, MAX_FAILURES, nextDelay } from '@/lib/model/poll';

export type Phase = 'loading' | 'running' | 'complete' | 'failed' | 'notfound' | 'lost';

export interface PollState {
  phase: Phase;
  scan: Scan | null;
  /** Failed reads in a row (reset by a good read). */
  failures: number;
}

type Stored = PollState & { key: string };

const phaseOf = (scan: Scan): Phase =>
  scan.status === 'COMPLETE' ? 'complete' : scan.status === 'FAILED' ? 'failed' : 'running';

export const scanCacheKey = (scanId: string): string => `scan:${scanId}`;

/**
 * Follows a scan until it is complete or failed (ui-core UI-PRG-1, UI-PRG-7). It reads at once, then after 1.5 s, and
 * the wait grows by half each time up to 5 s and starts again when the stage changes. It stops on COMPLETE or FAILED,
 * waits while the tab is hidden and reads again as soon as it is shown. A failed read is retried with the same
 * backoff; after five in a row the phase is `lost`. A 404 is `notfound`. A finished scan is read once per session.
 */
export function useScanPoll(
  scanId: string | null,
  client: Client = getClient(),
): PollState & { retry: () => void } {
  const [stored, setStored] = useState<Stored | null>(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const key = scanId === null ? null : `${scanId}#${attempt}`;
  const cached = scanId === null || attempt > 0 ? undefined : cacheGet<Scan>(scanCacheKey(scanId));

  useEffect(() => {
    if (scanId === null || key === null || cached !== undefined) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = FIRST_DELAY_MS;
    let failures = 0;
    let lastStage: string | null | undefined;
    let waitingForTab = false;
    let stopped = false;

    const publish = (state: PollState) => {
      if (!stopped) setStored({ key, ...state });
    };

    const schedule = (ms: number) => {
      timer = setTimeout(() => void tick(), ms);
    };

    const tick = async (): Promise<void> => {
      if (stopped) return;
      if (document.hidden) {
        waitingForTab = true; // read again as soon as the tab is shown
        return;
      }
      try {
        const scan = await client.getScan(scanId, controller.signal);
        if (stopped) return;
        failures = 0;
        publish({ phase: phaseOf(scan), scan, failures });
        if (scan.status === 'COMPLETE') cacheSet(scanCacheKey(scanId), scan);
        if (scan.status === 'COMPLETE' || scan.status === 'FAILED') return;
        delay = scan.stage === lastStage ? nextDelay(delay) : FIRST_DELAY_MS;
        lastStage = scan.stage;
        schedule(delay);
      } catch (error) {
        if (stopped) return;
        if (error instanceof ApiError && error.kind === 'problem' && error.status === 404) {
          publish({ phase: 'notfound', scan: null, failures });
          return;
        }
        failures += 1;
        if (failures >= MAX_FAILURES) {
          publish({ phase: 'lost', scan: null, failures });
          return;
        }
        delay = nextDelay(delay);
        setStored((s) => (s && s.key === key ? { ...s, failures } : s));
        schedule(delay);
      }
    };

    const onVisibility = () => {
      if (!document.hidden && waitingForTab) {
        waitingForTab = false;
        void tick();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    void tick();
    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [scanId, key, cached, client]);

  if (scanId === null) return { phase: 'loading', scan: null, failures: 0, retry };
  if (cached !== undefined) return { phase: phaseOf(cached), scan: cached, failures: 0, retry };
  if (stored && stored.key === key)
    return { phase: stored.phase, scan: stored.scan, failures: stored.failures, retry };
  return { phase: 'loading', scan: null, failures: 0, retry };
}
