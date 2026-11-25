import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
import { cacheGet } from '@/lib/api/cache';
import { useResource } from './use-resource';

describe('useResource', () => {
  it('stays loading while the key is not known yet', () => {
    const load = vi.fn();
    const { result } = renderHook(() => useResource(null, load));
    expect(result.current.status).toBe('loading');
    expect(load).not.toHaveBeenCalled();
  });

  it('loads once and returns the data', async () => {
    const load = vi.fn().mockResolvedValue({ a: 1 });
    const { result } = renderHook(() => useResource('k1', load));
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current).toMatchObject({ status: 'ready', data: { a: 1 } }));
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('caches only what the caller says is final, so a running scan is read again', async () => {
    const load = vi.fn(async () => ({ status: 'RUNNING' }));
    const first = renderHook(() => useResource('k-run', load, (v) => v.status === 'COMPLETE'));
    await waitFor(() => expect(first.result.current.status).toBe('ready'));
    expect(cacheGet('k-run')).toBeUndefined();
    first.unmount();
    const second = renderHook(() => useResource('k-run', load, (v) => v.status === 'COMPLETE'));
    await waitFor(() => expect(second.result.current.status).toBe('ready'));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('keeps a finished scan for the session and does not fetch it again', async () => {
    const load = vi.fn(async () => ({ status: 'COMPLETE' }));
    const final = (v: { status: string }) => v.status === 'COMPLETE';
    const first = renderHook(() => useResource('k-done', load, final));
    await waitFor(() => expect(first.result.current.status).toBe('ready'));
    first.unmount();
    const second = renderHook(() => useResource('k-done', load, final));
    expect(second.result.current).toMatchObject({ status: 'ready', data: { status: 'COMPLETE' } });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('reports an ApiError, and any other failure as a network error', async () => {
    const problem = renderHook(() =>
      useResource('k-p', () => Promise.reject(new ApiError('problem', 404))),
    );
    await waitFor(() => expect(problem.result.current.status).toBe('error'));
    expect((problem.result.current as { error: ApiError }).error.status).toBe(404);
    const odd = renderHook(() => useResource('k-o', () => Promise.reject(new Error('boom'))));
    await waitFor(() => expect(odd.result.current.status).toBe('error'));
    expect((odd.result.current as { error: ApiError }).error.kind).toBe('network');
  });

  it('loads again on reload and after a key change', async () => {
    const load = vi.fn().mockResolvedValueOnce(1).mockResolvedValueOnce(2).mockResolvedValue(3);
    const { result, rerender } = renderHook(({ k }) => useResource(k, load), {
      initialProps: { k: 'k-a' },
    });
    await waitFor(() => expect(result.current).toMatchObject({ data: 1 }));
    result.current.reload();
    await waitFor(() => expect(result.current).toMatchObject({ data: 2 }));
    rerender({ k: 'k-b' });
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current).toMatchObject({ data: 3 }));
  });

  it('ignores an answer that arrives after the component went away', async () => {
    let resolve: (v: number) => void = () => undefined;
    const load = vi.fn(() => new Promise<number>((r) => (resolve = r)));
    const { result, unmount } = renderHook(() => useResource('k-late', load, () => true));
    unmount();
    resolve(5);
    await Promise.resolve();
    expect(result.current.status).toBe('loading');
    expect(cacheGet('k-late')).toBeUndefined();
  });
});
