import { act, render, renderHook, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useRef } from 'react';
import { useFocusHeading, usePageTitle } from './use-page';
import { useQueryString } from './use-query-state';

describe('usePageTitle', () => {
  it('sets the title and ignores null', () => {
    document.title = 'before';
    const { rerender } = renderHook(({ t }) => usePageTitle(t), {
      initialProps: { t: null as string | null },
    });
    expect(document.title).toBe('before');
    rerender({ t: 'Graveyard · owner/name' });
    expect(document.title).toBe('Graveyard · owner/name');
  });
});

describe('useFocusHeading', () => {
  function Page({ ready, k }: { ready: boolean; k?: string }) {
    const ref = useRef<HTMLHeadingElement>(null);
    useFocusHeading(ref, ready, k);
    return (
      <h1 ref={ref} tabIndex={-1}>
        Title
      </h1>
    );
  }
  it('focuses the heading when the page is ready, and again when its content changes in place', () => {
    const { rerender } = render(<Page ready={false} />);
    expect(screen.getByRole('heading')).not.toHaveFocus();
    rerender(<Page ready />);
    expect(screen.getByRole('heading')).toHaveFocus();
    (document.activeElement as HTMLElement).blur();
    rerender(<Page ready k="complete" />);
    expect(screen.getByRole('heading')).toHaveFocus();
  });
});

describe('useQueryString', () => {
  it('reads the query, writes it without navigating, and follows popstate', () => {
    window.history.replaceState(null, '', '/scan?id=abc&view=scene');
    const { result } = renderHook(() => useQueryString());
    expect(result.current[0]).toBe('?id=abc&view=scene');
    act(() => result.current[1](new URLSearchParams('id=abc&view=table')));
    expect(result.current[0]).toBe('?id=abc&view=table');
    expect(window.location.pathname).toBe('/scan');
    act(() => {
      window.history.replaceState(null, '', '/scan?id=zzz');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(result.current[0]).toBe('?id=zzz');
  });
  it('drops the question mark when the query is empty', () => {
    window.history.replaceState(null, '', '/x?a=1');
    const { result } = renderHook(() => useQueryString());
    act(() => result.current[1](new URLSearchParams()));
    expect(window.location.search).toBe('');
  });
});
