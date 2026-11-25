import type { GraveSummary } from '@/lib/api/types';
import { nameOf, severityRank } from './grave';
import { byPriority } from './buckets';
import type { FilterKey, SortDir, SortKey } from './route';

/** A chip matches the base state, or an overlay: a dead and cursed package matches Dead and Cursed (design 4.7). */
export function matchesFilter(
  g: Pick<GraveSummary, 'state' | 'cursed' | 'wounded'>,
  filter: FilterKey | undefined,
): boolean {
  if (!filter) return true;
  if (filter === 'cursed') return g.cursed;
  if (filter === 'wounded') return g.wounded;
  return g.state === filter;
}

export function filterGraves<
  T extends Pick<GraveSummary, 'state' | 'cursed' | 'wounded' | 'services'>,
>(graves: readonly T[], filter: FilterKey | undefined, service?: string): T[] {
  return graves.filter(
    (g) => matchesFilter(g, filter) && (!service || g.services.includes(service)),
  );
}

const COLLATOR = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });

function compare(key: SortKey, a: GraveSummary, b: GraveSummary): number {
  if (key === 'priority') return byPriority(a, b);
  if (key === 'state') return severityRank(a) - severityRank(b) || byPriority(a, b);
  const na = nameOf(a);
  const nb = nameOf(b);
  return COLLATOR.compare(na.name, nb.name) || COLLATOR.compare(na.version, nb.version);
}

/**
 * The graves sorted by one column. The sort is stable and falls back to the purl, so the order is the same on every
 * render. `byPriority` already puts the highest first, so `desc` is its natural order; the other columns start with
 * the first. Graves with no priority stay last when sorting by priority, in both directions.
 */
export function sortGraves<T extends GraveSummary>(
  graves: readonly T[],
  key: SortKey,
  dir: SortDir,
): T[] {
  const natural: SortDir = key === 'priority' ? 'desc' : 'asc';
  const sign = dir === natural ? 1 : -1;
  return [...graves].sort((a, b) => {
    if (
      key === 'priority' &&
      (a.priority === null || b.priority === null) &&
      a.priority !== b.priority
    ) {
      return a.priority === null ? 1 : -1;
    }
    const result = compare(key, a, b) * sign;
    return result || (a.purl < b.purl ? -1 : a.purl > b.purl ? 1 : 0);
  });
}
