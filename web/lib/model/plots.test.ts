import { describe, expect, it } from 'vitest';
import type { Service } from '@/lib/api/types';
import { filterGraves } from './filter-sort';
import { attentionClass, buildPlots, plotTitle, restSentence, STONE_CAP } from './plots';
import { makeGrave } from './test-data';

const SERVICES: Service[] = [
  { id: '.', manifests: [{ ecosystem: 'npm', path: 'package-lock.json' }] },
  {
    id: 'services/worker',
    manifests: [{ ecosystem: 'pypi', path: 'services/worker/requirements.txt' }],
  },
  { id: 'services/clean', manifests: [{ ecosystem: 'pypi', path: 'services/clean/uv.lock' }] },
];

describe('plotTitle', () => {
  it.each([
    ['.', 'The root plot'],
    ['', 'The root plot'],
    ['services/worker', 'The worker plot'],
    ['api', 'The api plot'],
    ['a/b/', 'The b plot'],
  ])('%j', (id, title) => expect(plotTitle(id)).toBe(title));
});

describe('buildPlots', () => {
  const graves = [
    makeGrave({ purl: 'pkg:npm/a@1', priority: 90 }),
    makeGrave({ purl: 'pkg:npm/b@1', priority: 10 }),
    makeGrave({ purl: 'pkg:pypi/w@1', priority: 95, services: ['services/worker'] }),
    makeGrave({ purl: 'pkg:npm/shared@1', priority: 5, services: ['.', 'services/worker'] }),
  ];

  it('draws one plot per service, including a clean one', () => {
    const plots = buildPlots(SERVICES, graves);
    expect(plots.map((p) => p.id)).toEqual(['services/worker', '.', 'services/clean']);
    const clean = plots.find((p) => p.id === 'services/clean')!;
    expect(clean).toMatchObject({ clean: true, matching: 0, stones: [], hidden: 0 });
  });
  it('orders plots by their highest priority, then by id', () => {
    const plots = buildPlots(SERVICES, [makeGrave({ priority: 1 })]);
    expect(plots.map((p) => p.id)).toEqual(['.', 'services/clean', 'services/worker']);
  });
  it('writes the subtitle from the service, the ecosystem and the lockfile', () => {
    const plots = buildPlots(SERVICES, graves);
    expect(plots.find((p) => p.id === 'services/worker')!.subtitle).toBe(
      'service "services/worker" · PyPI · requirements.txt',
    );
    expect(plots.find((p) => p.id === '.')!.subtitle).toBe('service "." · npm · package-lock.json');
  });
  it('puts a package of two services in both plots', () => {
    const plots = buildPlots(SERVICES, graves);
    for (const id of ['.', 'services/worker']) {
      expect(plots.find((p) => p.id === id)!.stones.map((s) => s.purl)).toContain(
        'pkg:npm/shared@1',
      );
    }
  });
  it('sorts the stones by priority', () => {
    const root = buildPlots(SERVICES, graves).find((p) => p.id === '.')!;
    expect(root.stones.map((s) => s.priority)).toEqual([90, 10, 5]);
  });
  it('caps the stones and counts the rest', () => {
    const many = Array.from({ length: 133 }, (_, i) =>
      makeGrave({ purl: `pkg:npm/p${i}@1`, priority: i }),
    );
    const plot = buildPlots(SERVICES, many).find((p) => p.id === '.')!;
    expect(plot.stones).toHaveLength(STONE_CAP);
    expect(plot.hidden).toBe(109);
    expect(plot.matching).toBe(133);
    expect(plot.stones[0]!.priority).toBe(132);
  });
  it('tells a plot with no match from a clean plot', () => {
    const plots = buildPlots(SERVICES, graves, [graves[2]!]);
    const root = plots.find((p) => p.id === '.')!;
    expect(root).toMatchObject({ clean: false, matching: 0, stones: [] });
  });
  it('adds a plot for a service that is missing from the list', () => {
    const plots = buildPlots(SERVICES, [makeGrave({ services: ['tools/x'] })]);
    expect(plots.map((p) => p.id)).toContain('tools/x');
    expect(plots.find((p) => p.id === 'tools/x')!.subtitle).toBe('service "tools/x" · npm');
  });
  it('derives every plot from the graves for a scan without a service list', () => {
    const plots = buildPlots(null, graves);
    expect(plots.map((p) => p.id)).toEqual(['services/worker', '.']);
    expect(plots[0]).toMatchObject({ manifests: [], clean: false });
    expect(plots[0]!.subtitle).toBe('service "services/worker" · PyPI + npm');
  });
  it('gives no plots and no crash for an empty scan without services', () => {
    expect(buildPlots(null, [])).toEqual([]);
  });
});

describe('the order of the stones in a plot', () => {
  const g = (name: string, over: Parameters<typeof makeGrave>[0], priority: number) =>
    makeGrave({ purl: `pkg:npm/${name}@1`, priority, ...over });
  // Every class, each with a priority that would put it last if priority alone decided.
  const classes = [
    g('transitive-resting', { state: 'resting', direct: false }, 99),
    g('transitive-ailing', { state: 'ailing', direct: false }, 98),
    g('direct-resting', { state: 'resting', direct: true }, 97),
    g('direct-ailing', { state: 'ailing', direct: true }, 96),
    g('wounded', { state: 'alive', wounded: true, direct: false }, 3),
    g('dead', { state: 'dead', direct: false }, 2),
    g('cursed', { state: 'dead', cursed: true, direct: false }, 1),
  ];
  it('is cursed, dead, wounded, direct ailing, direct resting, transitive ailing, transitive resting', () => {
    const root = buildPlots(SERVICES, classes).find((p) => p.id === '.')!;
    expect(root.stones.map((x) => x.purl.slice(8, -2))).toEqual([
      'cursed',
      'dead',
      'wounded',
      'direct-ailing',
      'direct-resting',
      'transitive-ailing',
      'transitive-resting',
    ]);
  });
  it('orders by priority inside a class, and puts an alive or unscored package after the resting', () => {
    const more = [
      g('ailing-low', { state: 'ailing', direct: true }, 10),
      g('ailing-high', { state: 'ailing', direct: true }, 80),
      g('alive-direct', { state: 'alive', direct: true }, 99),
      g('unscored', { state: 'unscored', direct: true }, 99),
    ];
    const root = buildPlots(SERVICES, more).find((p) => p.id === '.')!;
    expect(root.stones.map((x) => x.purl.slice(8, -2))).toEqual([
      'ailing-high',
      'ailing-low',
      'alive-direct',
      'unscored',
    ]);
    expect(attentionClass(more[3]!)).toBe(7);
  });
  it('keeps a package with both overlays in the cursed class', () => {
    expect(attentionClass(makeGrave({ state: 'ailing', cursed: true, wounded: true }))).toBe(0);
  });
});

describe('the rest of a plot', () => {
  const many = (n: number, over: Parameters<typeof makeGrave>[0]) =>
    Array.from({ length: n }, (_, i) =>
      makeGrave({ purl: `pkg:npm/${over?.state}-${over?.direct}-${i}@1`, ...over }),
    );
  // 24 direct dead packages fill the cap; 52 transitive ailing, 9 transitive resting and 3 direct ailing are the rest.
  const all = [
    ...many(STONE_CAP, { state: 'dead', direct: true, priority: 100 }),
    ...many(3, { state: 'ailing', direct: true, priority: 40 }),
    ...many(52, { state: 'ailing', direct: false, priority: 30 }),
    ...many(9, { state: 'resting', direct: false, priority: 20 }),
  ];
  it('counts what is not drawn by state, in the order of attention', () => {
    const root = buildPlots(SERVICES, all).find((p) => p.id === '.')!;
    expect(root.hidden).toBe(64);
    expect(root.rest).toEqual({
      total: 64,
      byState: [
        { type: 'ailing', count: 55 },
        { type: 'resting', count: 9 },
      ],
      indirect: 61,
    });
    expect(restSentence(root.rest)).toBe(
      'Also in this plot: 55 ailing and 9 resting, mostly brought in by other packages',
    );
  });
  it('counts only the graves that match the filter', () => {
    const shown = filterGraves(all, 'resting');
    const root = buildPlots(SERVICES, all, shown).find((p) => p.id === '.')!;
    expect(root.hidden).toBe(0);
    expect(root.rest).toEqual({ total: 0, byState: [], indirect: 0 });
  });
  it('words one, two and three states, and leaves the clause out when most are direct', () => {
    expect(restSentence({ total: 3, byState: [{ type: 'ailing', count: 3 }], indirect: 1 })).toBe(
      'Also in this plot: 3 ailing',
    );
    expect(
      restSentence({
        total: 6,
        byState: [
          { type: 'dead', count: 1 },
          { type: 'wounded', count: 2 },
          { type: 'resting', count: 3 },
        ],
        indirect: 4,
      }),
    ).toBe(
      'Also in this plot: 1 dead, 2 wounded and 3 resting, mostly brought in by other packages',
    );
  });
});
