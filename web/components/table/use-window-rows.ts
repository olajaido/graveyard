'use client';
import { useCallback, useState, type UIEvent } from 'react';

/** Above this many rows the table renders a window of them (ui-core UI-TBL-5). At or below it, every row. */
export const WINDOW_THRESHOLD = 500;
export const ROW_HEIGHT = 49;
export const OVERSCAN = 10;
const FALLBACK_VIEWPORT = 600;

export interface RowWindow {
  windowed: boolean;
  /** First rendered row, and one past the last. */
  start: number;
  end: number;
  padTop: number;
  padBottom: number;
  onScroll: (event: UIEvent<HTMLElement>) => void;
}

/**
 * Which rows to render. Fixed row height, so the window is the visible range plus `OVERSCAN` rows each side, computed
 * from the scroll position of the table's region; spacer rows keep the scroll height. Below the threshold nothing is
 * windowed, so Tab order and the browser's find cover every row.
 */
export function useWindowRows(count: number): RowWindow {
  const [scroll, setScroll] = useState({ top: 0, height: FALLBACK_VIEWPORT });
  const onScroll = useCallback((event: UIEvent<HTMLElement>) => {
    const el = event.currentTarget;
    setScroll({ top: el.scrollTop, height: Math.max(FALLBACK_VIEWPORT, el.clientHeight) });
  }, []);
  if (count <= WINDOW_THRESHOLD) {
    return { windowed: false, start: 0, end: count, padTop: 0, padBottom: 0, onScroll };
  }
  const first = Math.floor(scroll.top / ROW_HEIGHT);
  const visible = Math.ceil(scroll.height / ROW_HEIGHT);
  const start = Math.max(0, first - OVERSCAN);
  const end = Math.min(count, first + visible + OVERSCAN);
  return {
    windowed: true,
    start,
    end,
    padTop: start * ROW_HEIGHT,
    padBottom: (count - end) * ROW_HEIGHT,
    onScroll,
  };
}
