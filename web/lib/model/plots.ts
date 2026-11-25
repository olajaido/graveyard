import type { GraveSummary, Service } from '@/lib/api/types';
import { byPriority } from './buckets';
import { displayOf, type GraveType } from './grave';
import { parseDisplayPurl } from './purl';

export const STONE_CAP = 24;

/**
 * The order of the stones in a plot: what needs a person first. Cursed, dead, wounded, then the ailing and the resting,
 * a direct dependency before one that another package brought in. Priority orders the stones within a class.
 * An alive package that is not wounded counts as resting; one with no state goes last.
 */
export function attentionClass(g: GraveSummary): number {
  const type = displayOf(g).type;
  if (type === 'cursed') return 0;
  if (type === 'dead') return 1;
  if (type === 'wounded') return 2;
  if (type === 'unknown') return 7;
  const ailing = type === 'ailing';
  if (g.direct) return ailing ? 3 : 4;
  return ailing ? 5 : 6;
}

/** `byPriority` inside the attention classes: the order the scene draws a plot in. */
export function byAttention(a: GraveSummary, b: GraveSummary): number {
  return attentionClass(a) - attentionClass(b) || byPriority(a, b);
}

/** The stones a plot does not draw, counted by state, for the line under the stones. */
export interface Rest {
  total: number;
  /** In the order of attention: cursed, dead, wounded, ailing, resting, alive, unscored. Zero counts are left out. */
  byState: { type: GraveType; count: number }[];
  /** How many of them another package brought in (not direct). */
  indirect: number;
}
const REST_ORDER: GraveType[] = [
  'cursed',
  'dead',
  'wounded',
  'ailing',
  'resting',
  'alive',
  'unknown',
];
function summariseRest(rest: readonly GraveSummary[]): Rest {
  const counts = new Map<GraveType, number>();
  for (const g of rest) counts.set(displayOf(g).type, (counts.get(displayOf(g).type) ?? 0) + 1);
  return {
    total: rest.length,
    byState: REST_ORDER.filter((t) => counts.has(t)).map((type) => ({
      type,
      count: counts.get(type)!,
    })),
    indirect: rest.filter((g) => !g.direct).length,
  };
}

export interface Plot {
  id: string;
  title: string;
  /** `service "services/worker" · PyPI · requirements.txt` */
  subtitle: string;
  ecosystems: string[];
  /** Lockfile names, the last segment of each manifest path. Empty when the scan has no service list. */
  manifests: string[];
  /** The graves that match the filter in the order of `byAttention`, at most `STONE_CAP`. */
  stones: GraveSummary[];
  /** How many matching graves are not drawn. */
  hidden: number;
  /** The graves that are not drawn, by state. */
  rest: Rest;
  /** How many graves match the filter in this plot. */
  matching: number;
  /** The plot has no graves at all (not only none that match): a clean service. */
  clean: boolean;
}

const LABELS: Record<string, string> = { npm: 'npm', pypi: 'PyPI' };

/** `.` is the root plot; any other service is named after its last path segment. */
export function plotTitle(id: string): string {
  if (id === '.' || id === '') return 'The root plot';
  const segment = id.split('/').filter(Boolean).pop() ?? id;
  return `The ${segment} plot`;
}

function lastSegment(path: string): string {
  return path.split('/').pop() ?? path;
}

/**
 * One plot per service of the scan, including a service with no graves (UI-GY-2). A grave whose service is missing
 * from the list adds a derived plot, and a scan without a list (`services` is null, a scan made before group B)
 * gets all its plots from the graves, without manifest names. A package in several services is in each of its plots.
 * `all` is every grave of the scan, `shown` the ones that match the filter.
 */
export function buildPlots(
  services: readonly Service[] | null,
  all: readonly GraveSummary[],
  shown: readonly GraveSummary[] = all,
): Plot[] {
  const known = new Map<string, { ecosystems: Set<string>; manifests: string[] }>();
  for (const s of services ?? []) {
    const entry = known.get(s.id) ?? { ecosystems: new Set<string>(), manifests: [] };
    for (const m of s.manifests) {
      entry.ecosystems.add(LABELS[m.ecosystem] ?? m.ecosystem);
      entry.manifests.push(lastSegment(m.path));
    }
    known.set(s.id, entry);
  }
  const byService = (graves: readonly GraveSummary[]) => {
    const map = new Map<string, GraveSummary[]>();
    for (const g of graves)
      for (const id of g.services.length ? g.services : ['(unknown service)']) {
        map.set(id, [...(map.get(id) ?? []), g]);
      }
    return map;
  };
  const allBy = byService(all);
  const shownBy = byService(shown);
  for (const id of allBy.keys())
    if (!known.has(id)) known.set(id, { ecosystems: new Set(), manifests: [] });

  const plots = [...known.entries()].map(([id, info]): Plot => {
    const inPlot = allBy.get(id) ?? [];
    const matches = [...(shownBy.get(id) ?? [])].sort(byAttention);
    const ecosystems = info.ecosystems.size
      ? [...info.ecosystems].sort()
      : [...new Set(inPlot.map((g) => parseDisplayPurl(g.purl).ecosystemLabel))].sort();
    const manifests = [...info.manifests].sort();
    return {
      id,
      title: plotTitle(id),
      subtitle: [`service "${id}"`, ecosystems.join(' + '), manifests.join(', ')]
        .filter(Boolean)
        .join(' · '),
      ecosystems,
      manifests,
      stones: matches.slice(0, STONE_CAP),
      hidden: Math.max(0, matches.length - STONE_CAP),
      rest: summariseRest(matches.slice(STONE_CAP)),
      matching: matches.length,
      clean: inPlot.length === 0,
    };
  });
  const top = (p: Plot): number => {
    const first = [...(allBy.get(p.id) ?? [])].sort(byPriority)[0]?.priority;
    return first ?? Number.NEGATIVE_INFINITY;
  };
  return plots.sort((a, b) => top(b) - top(a) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

const REST_WORD: Record<GraveType, string> = {
  cursed: 'cursed',
  dead: 'dead',
  wounded: 'wounded',
  ailing: 'ailing',
  resting: 'resting',
  alive: 'alive',
  unknown: 'unscored',
};

/**
 * "Also in this plot: 52 ailing and 9 resting, mostly brought in by other packages". The link to the table follows it.
 * The last clause is there only when more than half of the packages were brought in by another package.
 */
export function restSentence(rest: Rest): string {
  const parts = rest.byState.map(({ type, count }) => `${count} ${REST_WORD[type]}`);
  const list =
    parts.length <= 1 ? (parts[0] ?? '') : `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}`;
  const mostlyIndirect = rest.indirect * 2 > rest.total;
  return `Also in this plot: ${list}${mostlyIndirect ? ', mostly brought in by other packages' : ''}`;
}
