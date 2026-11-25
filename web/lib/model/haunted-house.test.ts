import { describe, expect, it } from 'vitest';
import { hauntedGraves, hauntedScan, lodashCertificate } from '@/mocks/fixtures/haunted-house';
import { rankGraves } from './buckets';
import { causeOf, causeOfDeath } from './cause';
import { displayOf, relationOf } from './grave';
import { attentionClass, buildPlots, restSentence, STONE_CAP } from './plots';
import { filterGraves } from './filter-sort';

const graves = hauntedGraves.items;

describe('the real haunted-house capture', () => {
  it('draws the stones of the root plot by attention class, cursed first, and says what the rest is', () => {
    const root = buildPlots(hauntedScan.services, graves).find((p) => p.id === '.')!;
    const classes = root.stones.map(attentionClass);
    expect(classes).toEqual([...classes].sort((a, b) => a - b));
    expect(root.stones.slice(0, 2).every((g) => g.cursed)).toBe(true);
    expect(root.rest.total).toBe(root.hidden);
    expect(restSentence(root.rest)).toBe(
      'Also in this plot: 80 ailing and 29 resting, mostly brought in by other packages',
    );
    // The rest never holds a package of a higher class than the last stone drawn.
    const drawn = new Set(root.stones.map((g) => g.purl));
    const rest = graves.filter((g) => g.services.includes('.') && !drawn.has(g.purl));
    expect(Math.min(...rest.map(attentionClass))).toBeGreaterThanOrEqual(classes.at(-1)!);
  });
  it('is what the counts say', () => {
    expect(graves).toHaveLength(hauntedGraves.total);
    expect(hauntedScan.counts).toMatchObject({
      total: 208,
      dead: 17,
      cursed: 2,
      ailing: 84,
      resting: 31,
      wounded: 5,
    });
    const by = (state: string) => graves.filter((g) => g.state === state).length;
    expect([by('dead'), by('ailing'), by('resting')]).toEqual([17, 84, 31]);
    expect(graves.filter((g) => g.cursed)).toHaveLength(2);
    expect(graves.filter((g) => g.wounded)).toHaveLength(5);
    expect(hauntedScan.stage).toBe('DONE');
    expect(hauntedScan.progress).toBeNull();
  });

  it('draws two plots from the service list and caps the root plot', () => {
    const plots = buildPlots(hauntedScan.services, graves);
    expect(plots.map((p) => p.id)).toEqual(['.', 'services/worker']);
    const [root, worker] = plots;
    expect(root).toMatchObject({ title: 'The root plot', matching: 133, hidden: 133 - STONE_CAP });
    expect(root!.stones).toHaveLength(24);
    expect(root!.subtitle).toBe('service "." · npm · package-lock.json');
    expect(worker).toMatchObject({ title: 'The worker plot', matching: 4, hidden: 0 });
    expect(worker!.subtitle).toBe('service "services/worker" · PyPI · requirements.txt');
  });

  it('sizes the stones in four buckets and keeps ties together', () => {
    const ranks = rankGraves(graves);
    const buckets = new Set([...ranks.values()].map((r) => r.bucket));
    expect([...buckets].sort()).toEqual([0, 1, 2, 3]);
    const nine = graves.filter((g) => g.priority === 90);
    expect(nine.length).toBeGreaterThan(1);
    expect(new Set(nine.map((g) => ranks.get(g.purl)!.bucket)).size).toBe(1);
    const first = ranks.get('pkg:npm/lodash.template@3.6.2')!;
    expect(first).toMatchObject({ position: 1, total: 137, bucket: 0 });
  });

  it('draws the cursed packages as cursed graves and the wounded alive ones as saplings', () => {
    const cursed = graves
      .filter((g) => displayOf(g).type === 'cursed')
      .map((g) => g.purl)
      .sort();
    expect(cursed).toEqual(['pkg:npm/lodash.template@3.6.2', 'pkg:npm/request@2.88.2']);
    const wounded = graves.filter((g) => displayOf(g).type === 'wounded');
    expect(wounded).toHaveLength(5);
    expect(wounded.every((g) => g.state === 'alive')).toBe(true);
  });

  it('knows who brought each package in', () => {
    const lodash = graves.find((g) => g.purl === 'pkg:npm/lodash.template@3.6.2')!;
    expect(relationOf(lodash)).toEqual({ kind: 'via', text: 'via gulp-util', via: 'gulp-util' });
    const direct = graves.filter((g) => g.direct);
    expect(direct.length).toBeGreaterThan(0);
    expect(direct.every((g) => relationOf(g).kind === 'direct')).toBe(true);
  });

  it('filters by chip and by service', () => {
    expect(filterGraves(graves, 'cursed')).toHaveLength(2);
    expect(filterGraves(graves, 'dead')).toHaveLength(17);
    expect(filterGraves(graves, undefined, 'services/worker')).toHaveLength(4);
  });

  it('gives every grave a cause the table can print', () => {
    expect(causeOf(lodashCertificate)).toBe(
      'Declared dead by its source; Known vulnerability, no fix available',
    );
    expect(causeOfDeath(lodashCertificate)).toContain('A known vulnerability affects this version');
  });
});
