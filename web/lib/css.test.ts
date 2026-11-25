import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(process.cwd(), 'app/globals.css'), 'utf8');

/** Top-level rules of the file: the selector and the body of each block that is not inside an at-rule block. */
function topLevelRules(source: string): { selector: string; body: string }[] {
  const out: { selector: string; body: string }[] = [];
  let depth = 0;
  let start = 0;
  let selector = '';
  const text = source.replace(/\/\*[\s\S]*?\*\//g, '');
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '{') {
      if (depth === 0) selector = text.slice(start, i).trim();
      depth++;
      if (depth === 1) start = i + 1;
    } else if (ch === '}') {
      depth--;
      if (depth === 0) {
        out.push({ selector, body: text.slice(start, i) });
        start = i + 1;
      }
    }
  }
  return out;
}

describe('the cascade of globals.css', () => {
  const rules = topLevelRules(css).filter((r) => !r.selector.startsWith('@'));
  it('has no plain rule that sets the colour of a link: unlayered CSS would beat every text-* utility on an anchor', () => {
    const bad = rules.filter(
      (r) => /(^|[\s,>+~])a(\s*[,:[.#]|\s*$)/.test(r.selector) && /(^|[;\s])color\s*:/.test(r.body),
    );
    expect(bad).toEqual([]);
  });
  it('has no unlayered rule that sets a text colour on any element selector', () => {
    const bad = rules.filter(
      (r) =>
        /^[a-z][a-z0-9]*$/.test(r.selector) &&
        !['body', 'html'].includes(r.selector) &&
        /(^|[;\s])color\s*:/.test(r.body),
    );
    expect(bad).toEqual([]);
  });
  it('draws no focus ring on a heading or region that script focuses, and keeps it on real controls', () => {
    const quiet = rules.find(
      (r) => r.selector.includes(`[tabindex='-1']`) && r.selector.endsWith(':focus'),
    );
    expect(quiet?.body).toMatch(/outline\s*:\s*none/);
    expect(quiet?.selector).toContain(':not(a, button, input, select, textarea, summary)');
    const ring = rules.find(
      (r) => r.selector.includes(':focus-visible') && r.selector.includes('[tabindex]'),
    );
    expect(ring?.body).toMatch(/outline\s*:\s*2px solid var\(--focus\)/);
    expect(ring?.selector).toContain('a, button');
  });
});
