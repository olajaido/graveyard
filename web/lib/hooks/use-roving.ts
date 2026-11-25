'use client';
import { useCallback, useRef, useState, type KeyboardEvent } from 'react';

/** The element of `items` nearest to `from` in the row above (`-1`) or below (`1`), by their boxes. */
export function nearestInRow(
  items: readonly HTMLElement[],
  from: number,
  direction: -1 | 1,
): number {
  const here = items[from]?.getBoundingClientRect();
  if (!here) return from;
  const cx = here.left + here.width / 2;
  let best = from;
  let bestRowDistance = Number.POSITIVE_INFINITY;
  let bestColumnDistance = Number.POSITIVE_INFINITY;
  items.forEach((el, i) => {
    const r = el.getBoundingClientRect();
    const dy = (r.top - here.top) * direction;
    if (dy <= 8) return; // not in the row above (or below)
    const column = Math.abs(r.left + r.width / 2 - cx);
    if (
      dy < bestRowDistance - 8 ||
      (Math.abs(dy - bestRowDistance) <= 8 && column < bestColumnDistance)
    ) {
      best = i;
      bestRowDistance = dy;
      bestColumnDistance = column;
    }
  });
  return best;
}

/**
 * Roving tabindex for a group of links (ui-core UI-GY-7): one tab stop per group, the arrow keys move between the
 * items, Home and End jump to the first and the last. Left and Right move by one, Up and Down to the nearest item in
 * the row above or below. `itemSelector` finds the items in the group's element.
 */
export function useRoving(itemSelector: string) {
  const group = useRef<HTMLElement | null>(null);
  const [active, setActive] = useState(0);

  const items = useCallback(
    (): HTMLElement[] => [...(group.current?.querySelectorAll<HTMLElement>(itemSelector) ?? [])],
    [itemSelector],
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent, index: number) => {
      const all = items();
      let next = index;
      switch (event.key) {
        case 'ArrowRight':
          next = Math.min(all.length - 1, index + 1);
          break;
        case 'ArrowLeft':
          next = Math.max(0, index - 1);
          break;
        case 'ArrowDown':
          next = nearestInRow(all, index, 1);
          break;
        case 'ArrowUp':
          next = nearestInRow(all, index, -1);
          break;
        case 'Home':
          next = 0;
          break;
        case 'End':
          next = all.length - 1;
          break;
        default:
          return;
      }
      event.preventDefault();
      setActive(next);
      all[next]?.focus();
    },
    [items],
  );

  return {
    groupRef: group,
    /** Clamped, so a shorter list after a filter never leaves the group without a tab stop. */
    tabIndexFor: (index: number, count: number) =>
      index === Math.min(active, Math.max(0, count - 1)) ? 0 : -1,
    onKeyDown,
    setActive,
  };
}
