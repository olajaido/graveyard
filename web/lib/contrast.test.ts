import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { contrastRatio, parseColorTokens } from './contrast';

const css = readFileSync(resolve(process.cwd(), 'app/globals.css'), 'utf8');
const t = parseColorTokens(css);
const c = (name: string): string => {
  const hex = t[name];
  if (!hex) throw new Error(`token ${name} is not in globals.css`);
  return hex;
};

const STATES = ['dead', 'cursed', 'ailing', 'resting', 'alive', 'wounded'] as const;
const DARK = ['ground', 'night', 'night-alt', 'surface', 'plot'] as const;
const TEXT = ['bone', 'bone-soft', 'bone-muted', 'bone-quiet'] as const;

describe('tokens', () => {
  it('match the hex values of frontend-design.md', () => {
    expect(t).toMatchObject({
      ground: '#0d0f13',
      night: '#121620',
      surface: '#161a21',
      stone: '#2a2f37',
      bone: '#ece6d8',
      parchment: '#ede6d6',
      ink: '#1b1a17',
      dead: '#e8887b',
      cursed: '#c4aef5',
      ailing: '#e9b266',
      resting: '#8fb2e0',
      alive: '#93cba6',
      wounded: '#f0a39a',
      'dead-ink': '#8a2b1f',
      'cursed-ink': '#4e3a86',
      'ailing-ink': '#7a4a0e',
      'resting-ink': '#2d4b78',
      'alive-ink': '#2f6b44',
      'wounded-ink': '#8a3a30',
      'paper-tint': '#e3daca',
    });
  });
});

describe('text contrast (AA, 4.5:1)', () => {
  const pairs: [string, string][] = [];
  for (const bg of [...DARK, 'stone']) for (const fg of TEXT) pairs.push([fg, bg]);
  for (const bg of [...DARK, 'stone']) for (const s of STATES) pairs.push([s, bg]);
  for (const bg of DARK) pairs.push(['bone-dim', bg]);
  // The plot title and subtitle sit over the lighter hill of the plot backdrop (`hairline`).
  for (const fg of TEXT) pairs.push([fg, 'hairline']);
  pairs.push(['stone-text', 'stone'], ['on-bone', 'bone'], ['flame', 'ground'], ['flame', 'night']);
  for (const fg of ['ink', 'ink-soft', 'ink-muted', 'paper-link']) {
    pairs.push([fg, 'parchment'], [fg, 'paper-tint']);
  }
  for (const s of STATES) pairs.push([`${s}-ink`, 'parchment'], [`${s}-ink`, `${s}-pill`]);
  pairs.push(['seal-text', 'seal']);

  it.each(pairs)('%s on %s', (fg, bg) => {
    expect(contrastRatio(c(fg), c(bg))).toBeGreaterThanOrEqual(4.5);
  });
});

describe('non-text contrast (3:1)', () => {
  it.each([...DARK, 'stone'].flatMap((bg) => ['bone'].map((fg) => [fg, bg] as [string, string])))(
    'focus ring %s on %s',
    (fg, bg) => {
      expect(contrastRatio(c(fg), c(bg))).toBeGreaterThanOrEqual(3);
    },
  );
  it('the ink focus ring is visible on parchment and its tint', () => {
    expect(contrastRatio(c('ink'), c('parchment'))).toBeGreaterThanOrEqual(3);
    expect(contrastRatio(c('ink'), c('paper-tint'))).toBeGreaterThanOrEqual(3);
  });
  it.each(STATES.filter((s) => s !== 'wounded'))('the %s stroke on a grave body', (s) => {
    expect(contrastRatio(c(s), c('stone'))).toBeGreaterThanOrEqual(3);
  });
});

describe('the documented failures stay excluded', () => {
  it('bone-dim fails on stone, so it must never be used there', () => {
    expect(contrastRatio(c('bone-dim'), c('stone'))).toBeLessThan(4.5);
  });
  it('the bone ring on parchment would be invisible', () => {
    expect(contrastRatio(c('bone'), c('parchment'))).toBeLessThan(1.5);
  });
  it('the double rule on paper is decoration only', () => {
    expect(contrastRatio(c('paper-rule-strong'), c('parchment'))).toBeLessThan(4.5);
  });
});
