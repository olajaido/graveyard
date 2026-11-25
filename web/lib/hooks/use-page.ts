'use client';
import { useEffect, type RefObject } from 'react';

/** Sets `document.title` (ui-core UI-RT-5). Pass `null` while the title is not known yet. */
export function usePageTitle(title: string | null): void {
  useEffect(() => {
    if (title) document.title = title;
  }, [title]);
}

/**
 * Moves focus to the page heading once the page has something to say (UI-RT-5), so a screen reader user lands on the
 * new page's `<h1>` after a navigation. The heading needs `tabIndex={-1}`. `key` changes when the content changes in
 * place (a scan that completes), so focus follows it.
 */
export function useFocusHeading(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  key: string = '',
): void {
  useEffect(() => {
    if (active) ref.current?.focus({ preventScroll: false });
  }, [ref, active, key]);
}
