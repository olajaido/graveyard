import { expect } from 'vitest';

/** Exactly one h1, and no heading level skipped on the way down (WCAG 1.3.1, ui-core UI-Q-1). */
export function expectHeadingOrder(root: ParentNode = document): void {
  const levels = [...root.querySelectorAll('h1,h2,h3,h4,h5,h6')].map((h) => Number(h.tagName[1]));
  expect(levels.filter((l) => l === 1)).toHaveLength(1);
  levels.forEach((level, i) => {
    if (i > 0)
      expect(level, `heading ${i} jumps from h${levels[i - 1]} to h${level}`).toBeLessThanOrEqual(
        levels[i - 1]! + 1,
      );
  });
}

/** Every svg is decorative (`aria-hidden`) unless it has an accessible name (ui-core UI-Q-5). */
export function expectDecorativeSvgs(root: ParentNode = document): void {
  for (const svg of root.querySelectorAll('svg')) {
    const named =
      svg.hasAttribute('aria-label') ||
      svg.hasAttribute('aria-labelledby') ||
      svg.querySelector('title');
    expect(
      svg.getAttribute('aria-hidden') === 'true' || named,
      `svg ${svg.outerHTML.slice(0, 80)}`,
    ).toBeTruthy();
  }
}

/** Controls are native and named: no clickable div, every button and link has a name, every field a label. */
export function expectNativeControls(root: ParentNode = document): void {
  for (const el of root.querySelectorAll('[onclick], div[role="button"], span[role="button"]')) {
    throw new Error(`a clickable ${el.tagName} instead of a button or a link`);
  }
  for (const el of root.querySelectorAll('button, a[href]')) {
    const name = (el.getAttribute('aria-label') ?? el.textContent ?? '').trim();
    expect(
      name.length,
      `a ${el.tagName} with no name: ${el.outerHTML.slice(0, 100)}`,
    ).toBeGreaterThan(0);
  }
  for (const el of root.querySelectorAll('input:not([type="hidden"]), select, textarea')) {
    const id = el.getAttribute('id');
    const labelled =
      el.hasAttribute('aria-label') ||
      el.hasAttribute('aria-labelledby') ||
      (id !== null && root.querySelector(`label[for="${id}"]`) !== null) ||
      el.closest('label') !== null;
    expect(labelled, `an unlabelled field: ${el.outerHTML.slice(0, 100)}`).toBe(true);
  }
}

/** A tab through the page reaches only real, visible, focusable things, and never loops back inside it. */
export function tabbables(root: ParentNode = document): HTMLElement[] {
  return [
    ...root.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]',
    ),
  ].filter((el) => el.getAttribute('tabindex') !== '-1');
}
