import { describe, expect, it } from 'vitest';
import { displayOf, nameOf, relationOf, severityRank } from './grave';
import { makeGrave } from './test-data';

type Base = 'alive' | 'resting' | 'ailing' | 'dead' | 'unknown';

// Every state against both overlays, as PRD 7.4 reads (as amended for model v2): [state, cursed, wounded, type, label].
const TABLE: [Base, boolean, boolean, string, string][] = [
  ['dead', false, false, 'dead', 'dead'],
  ['dead', true, false, 'cursed', 'dead · cursed'],
  ['dead', false, true, 'dead', 'dead · wounded'],
  ['dead', true, true, 'cursed', 'dead · cursed'],
  ['ailing', false, false, 'ailing', 'ailing'],
  ['ailing', true, false, 'cursed', 'ailing · cursed'],
  ['ailing', false, true, 'ailing', 'ailing · wounded'],
  ['ailing', true, true, 'cursed', 'ailing · cursed'],
  ['resting', false, false, 'resting', 'resting'],
  ['resting', true, false, 'cursed', 'resting · cursed'],
  ['resting', false, true, 'wounded', 'resting · wounded'],
  ['resting', true, true, 'cursed', 'resting · cursed'],
  ['alive', false, false, 'alive', 'alive'],
  ['alive', true, false, 'cursed', 'alive · cursed'],
  ['alive', false, true, 'wounded', 'alive · wounded'],
  ['alive', true, true, 'cursed', 'alive · cursed'],
  ['unknown', false, false, 'unknown', 'unknown'],
  ['unknown', false, true, 'wounded', 'unknown · wounded'],
  ['unknown', true, false, 'cursed', 'unknown · cursed'],
];

describe('displayOf', () => {
  it.each(TABLE)('%s, cursed %s, wounded %s', (state, cursed, wounded, type, label) => {
    const d = displayOf({ state, cursed, wounded });
    expect(d.type).toBe(type);
    expect(d.label).toBe(label);
    expect(d.base).toBe(state);
  });
  it('shows Cursed only when both overlays are true', () => {
    expect(displayOf({ state: 'dead', cursed: true, wounded: true }).overlays).toEqual(['cursed']);
  });
  it('writes words for accessible names', () => {
    expect(displayOf({ state: 'dead', cursed: true, wounded: false }).words).toBe(
      'Dead and cursed',
    );
    expect(displayOf({ state: 'alive', cursed: false, wounded: true }).words).toBe(
      'Alive and wounded',
    );
    expect(displayOf({ state: 'resting', cursed: false, wounded: false }).words).toBe('Resting');
  });
  it('treats an unscored node as unknown', () => {
    expect(displayOf({ state: 'unscored', cursed: false, wounded: false }).type).toBe('unknown');
  });
  it('is total for the states the API can send', () => {
    for (const state of ['alive', 'resting', 'ailing', 'dead', 'unknown', 'unscored'] as const) {
      expect(displayOf({ state, cursed: false, wounded: false }).type).toBeTruthy();
    }
  });
});

describe('severityRank', () => {
  it('orders cursed, dead, ailing, resting, wounded, alive, unknown', () => {
    const order = [
      { state: 'alive', cursed: true, wounded: false },
      { state: 'dead', cursed: false, wounded: false },
      { state: 'ailing', cursed: false, wounded: false },
      { state: 'resting', cursed: false, wounded: false },
      { state: 'alive', cursed: false, wounded: true },
      { state: 'alive', cursed: false, wounded: false },
      { state: 'unknown', cursed: false, wounded: false },
    ] as const;
    const ranks = order.map((g) => severityRank(g));
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
    expect(new Set(ranks).size).toBe(7);
  });
});

describe('relationOf', () => {
  it('is direct for a direct dependency, even with a via', () => {
    expect(relationOf({ direct: true, via: 'pkg:npm/a@1' })).toEqual({
      kind: 'direct',
      text: 'direct',
    });
  });
  it('names the introducer', () => {
    expect(relationOf({ direct: false, via: 'pkg:npm/gulp-util@3.0.8' })).toEqual({
      kind: 'via',
      text: 'via gulp-util',
      via: 'gulp-util',
    });
    expect(relationOf({ direct: false, via: 'pkg:npm/%40babel/core@7.0.0' }).text).toBe(
      'via @babel/core',
    );
  });
  it('is transitive when no path was kept', () => {
    expect(relationOf({ direct: false, via: null })).toEqual({
      kind: 'transitive',
      text: 'transitive',
    });
  });
});

describe('nameOf', () => {
  it('splits name and version', () => {
    expect(nameOf(makeGrave({ purl: 'pkg:pypi/pycrypto@2.6.1' }))).toEqual({
      name: 'pycrypto',
      version: '2.6.1',
    });
  });
});
