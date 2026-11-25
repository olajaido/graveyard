import axe from 'axe-core';
import { expect } from 'vitest';

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'];

/**
 * axe-core on a rendered container, with the WCAG 2.2 AA tags (ui-core UI-TEST-3). jsdom has no layout, so the
 * colour contrast rule cannot run here: contrast is tested from the tokens (lib/contrast.test.ts) and, in a real
 * browser, by the Playwright smoke. `region` is off for fragments that are not a whole page.
 */
export async function expectNoViolations(
  container: Element,
  options: { wholePage?: boolean } = {},
): Promise<void> {
  const results = await axe.run(container, {
    runOnly: { type: 'tag', values: TAGS },
    rules: {
      'color-contrast': { enabled: false },
      region: { enabled: options.wholePage === true },
      // A test renders one page into a div: the document-level rules belong to the whole-page Playwright run.
      'landmark-one-main': { enabled: options.wholePage === true },
      'page-has-heading-one': { enabled: options.wholePage === true },
    },
  });
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`,
  );
  expect(summary).toEqual([]);
}
