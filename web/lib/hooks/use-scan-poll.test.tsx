import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cacheGet } from '@/lib/api/cache';
import { ApiError, type Client } from '@/lib/api/client';
import type { Scan } from '@/lib/api/types';
import { completeScan, failedScan, runningScan } from '@/mocks/fixtures/builders';
import { HAUNTED_SCAN_ID } from '@/mocks/fixtures/haunted-house';
import { scanCacheKey, useScanPoll } from './use-scan-poll';

function fakeClient(answers: (Scan | ApiError)[]) {
  const times: number[] = [];
  const getScan = vi.fn(async () => {
    times.push(Date.now());
    const next = answers[Math.min(times.length - 1, answers.length - 1)]!;
    if (next instanceof ApiError) throw next;
    return next;
  });
  return { client: { getScan } as unknown as Client, getScan, times };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
}

beforeEach(() => {
  vi.useFakeTimers();
  setHidden(false);
});
afterEach(() => {
  vi.useRealTimers();
});

describe('useScanPoll', () => {
  it('reads at once, then waits 1.5, 2.25, 3.4 and 5 seconds while the stage stays the same', async () => {
    const running = runningScan('FETCH');
    const { client, times } = fakeClient([running]);
    const { unmount } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(0);
    await advance(30_000);
    const gaps = times.slice(1).map((t, i) => t - times[i]!);
    expect(gaps.slice(0, 6)).toEqual([1500, 2250, 3375, 5000, 5000, 5000]);
    unmount();
  });

  it('starts the wait again when the stage changes', async () => {
    const { client, times } = fakeClient([
      runningScan('FETCH'),
      runningScan('FETCH'),
      runningScan('FETCH'),
      runningScan('SBOM'),
      runningScan('SBOM'),
    ]);
    const { unmount } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(0);
    await advance(20_000);
    const gaps = times.slice(1, 5).map((t, i) => t - times[i]!);
    expect(gaps).toEqual([1500, 2250, 3375, 1500]);
    unmount();
  });

  it('stops on COMPLETE, keeps the finished scan for the session and reports complete', async () => {
    const { client, getScan } = fakeClient([runningScan('CLASSIFY'), completeScan()]);
    const { result } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(0);
    expect(result.current.phase).toBe('running');
    await advance(1500);
    expect(result.current.phase).toBe('complete');
    expect(result.current.scan?.counts?.total).toBe(208);
    await advance(60_000);
    expect(getScan).toHaveBeenCalledTimes(2);
    expect(cacheGet(scanCacheKey(HAUNTED_SCAN_ID))).toBeDefined();
  });

  it('goes straight to results for a finished scan it already has', async () => {
    const first = fakeClient([completeScan()]);
    const a = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, first.client));
    await advance(0);
    a.unmount();
    const second = fakeClient([runningScan('FETCH')]);
    const b = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, second.client));
    expect(b.result.current.phase).toBe('complete');
    await advance(10_000);
    expect(second.getScan).not.toHaveBeenCalled();
  });

  it('stops on FAILED and never caches it', async () => {
    const { client, getScan } = fakeClient([failedScan('NO_MANIFESTS', 'FETCH')]);
    const { result } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(0);
    expect(result.current.phase).toBe('failed');
    expect(result.current.scan?.error?.code).toBe('NO_MANIFESTS');
    await advance(30_000);
    expect(getScan).toHaveBeenCalledTimes(1);
    expect(cacheGet(scanCacheKey(HAUNTED_SCAN_ID))).toBeUndefined();
  });

  it('does not read while the tab is hidden, and reads at once when it is shown', async () => {
    const { client, getScan } = fakeClient([runningScan('FETCH')]);
    const { unmount } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(0);
    expect(getScan).toHaveBeenCalledTimes(1);
    setHidden(true);
    await advance(20_000);
    expect(getScan).toHaveBeenCalledTimes(1); // the read that fell due while hidden was skipped
    await advance(20_000);
    expect(getScan).toHaveBeenCalledTimes(1);
    setHidden(false);
    await advance(0);
    expect(getScan).toHaveBeenCalledTimes(2);
    unmount();
  });

  it('retries a failed read with the same backoff, then gives up after five in a row', async () => {
    const { client, getScan, times } = fakeClient([new ApiError('network')]);
    const { result } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(0);
    expect(result.current.phase).toBe('loading');
    await advance(30_000);
    expect(getScan).toHaveBeenCalledTimes(5);
    expect(result.current.phase).toBe('lost');
    expect(times.slice(1).map((t, i) => t - times[i]!)).toEqual([2250, 3375, 5000, 5000]);
    await advance(60_000);
    expect(getScan).toHaveBeenCalledTimes(5);
  });

  it('forgets earlier failures after a good read', async () => {
    const { client, getScan } = fakeClient([
      new ApiError('network'),
      new ApiError('problem', 503),
      runningScan('FETCH'),
      new ApiError('network'),
      new ApiError('network'),
      new ApiError('network'),
      new ApiError('network'),
      completeScan(),
    ]);
    const { result } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(120_000);
    expect(getScan.mock.calls.length).toBeGreaterThanOrEqual(8);
    expect(result.current.phase).toBe('complete');
  });

  it('retry starts again after the trail was lost', async () => {
    const { client, getScan } = fakeClient([
      new ApiError('network'),
      new ApiError('network'),
      new ApiError('network'),
      new ApiError('network'),
      new ApiError('network'),
      completeScan(),
    ]);
    const { result } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(60_000);
    expect(result.current.phase).toBe('lost');
    act(() => result.current.retry());
    await advance(0);
    expect(result.current.phase).toBe('complete');
    expect(getScan).toHaveBeenCalledTimes(6);
  });

  it('reports a scan the API does not know as not found, without retrying', async () => {
    const { client, getScan } = fakeClient([new ApiError('problem', 404)]);
    const { result } = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(0);
    expect(result.current.phase).toBe('notfound');
    await advance(30_000);
    expect(getScan).toHaveBeenCalledTimes(1);
  });

  it('does nothing until it has an id, and cancels on unmount', async () => {
    const { client, getScan } = fakeClient([runningScan('FETCH')]);
    const none = renderHook(() => useScanPoll(null, client));
    await advance(10_000);
    expect(getScan).not.toHaveBeenCalled();
    expect(none.result.current.phase).toBe('loading');
    const real = renderHook(() => useScanPoll(HAUNTED_SCAN_ID, client));
    await advance(0);
    real.unmount();
    const calls = getScan.mock.calls.length;
    await advance(30_000);
    expect(getScan).toHaveBeenCalledTimes(calls);
  });
});
