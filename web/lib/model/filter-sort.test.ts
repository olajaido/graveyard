import { describe, expect, it } from 'vitest';
import { filterGraves, matchesFilter, sortGraves } from './filter-sort';
import { makeGrave } from './test-data';

const A = makeGrave({ purl: 'pkg:npm/alpha@1.10.0', state: 'dead', priority: 90, cursed: false });
const B = makeGrave({ purl: 'pkg:npm/beta@2.0.0', state: 'ailing', priority: 40 });
const C = makeGrave({
  purl: 'pkg:npm/gamma@1.0.0',
  state: 'alive',
  wounded: true,
  priority: 3,
  services: ['services/worker'],
});
const D = makeGrave({ purl: 'pkg:npm/delta@1.0.0', state: 'dead', cursed: true, priority: 108 });
const E = makeGrave({ purl: 'pkg:npm/eps@1.0.0', state: 'resting', priority: null });
const ALL = [A, B, C, D, E];

describe('filters', () => {
  it('match the base state or an overlay', () => {
    expect(matchesFilter(D, 'dead')).toBe(true);
    expect(matchesFilter(D, 'cursed')).toBe(true);
    expect(matchesFilter(D, 'ailing')).toBe(false);
    expect(matchesFilter(C, 'wounded')).toBe(true);
    expect(matchesFilter(C, 'alive' as never)).toBe(true);
    expect(matchesFilter(A, undefined)).toBe(true);
  });
  it('filter a list by chip and by service', () => {
    expect(filterGraves(ALL, 'dead').map((g) => g.purl)).toEqual([A.purl, D.purl]);
    expect(filterGraves(ALL, undefined, 'services/worker')).toEqual([C]);
    expect(filterGraves(ALL, 'wounded', '.')).toEqual([]);
  });
});

describe('sortGraves', () => {
  const names = (list: typeof ALL) => list.map((g) => g.purl.split('/')[1]!.split('@')[0]);
  it('sorts by priority, highest first, with a missing priority last in both directions', () => {
    expect(names(sortGraves(ALL, 'priority', 'desc'))).toEqual([
      'delta',
      'alpha',
      'beta',
      'gamma',
      'eps',
    ]);
    expect(names(sortGraves(ALL, 'priority', 'asc'))).toEqual([
      'gamma',
      'beta',
      'alpha',
      'delta',
      'eps',
    ]);
  });
  it('sorts by package name, then by version in number order', () => {
    const versions = [
      makeGrave({ purl: 'pkg:npm/same@1.10.0' }),
      makeGrave({ purl: 'pkg:npm/same@1.9.0' }),
      makeGrave({ purl: 'pkg:npm/a@2.0.0' }),
    ];
    expect(sortGraves(versions, 'package', 'asc').map((g) => g.purl)).toEqual([
      'pkg:npm/a@2.0.0',
      'pkg:npm/same@1.9.0',
      'pkg:npm/same@1.10.0',
    ]);
    expect(sortGraves(versions, 'package', 'desc')[0]!.purl).toBe('pkg:npm/same@1.10.0');
  });
  it('sorts by state: cursed, dead, ailing, resting, wounded, alive', () => {
    expect(names(sortGraves(ALL, 'state', 'asc'))).toEqual([
      'delta',
      'alpha',
      'beta',
      'eps',
      'gamma',
    ]);
    expect(names(sortGraves(ALL, 'state', 'desc'))).toEqual([
      'gamma',
      'eps',
      'beta',
      'alpha',
      'delta',
    ]);
  });
  it('is stable and does not change its input', () => {
    const same = [
      makeGrave({ purl: 'pkg:npm/b@1', priority: 5 }),
      makeGrave({ purl: 'pkg:npm/a@1', priority: 5 }),
    ];
    const copy = [...same];
    expect(sortGraves(same, 'priority', 'desc').map((g) => g.purl)).toEqual([
      'pkg:npm/a@1',
      'pkg:npm/b@1',
    ]);
    expect(same).toEqual(copy);
  });
});
