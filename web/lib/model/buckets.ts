import type { GraveSummary } from '@/lib/api/types';

/** Widths of the four sizes, in px. The height is the width times 160 / 120 (frontend-design.md section 5). */
export const WIDTHS = [150, 124, 104, 86] as const;

export interface Rank {
  /** 1-based place in the list sorted by priority, highest first. */
  position: number;
  total: number;
  /** 0 is the biggest stone. */
  bucket: 0 | 1 | 2 | 3;
}

export function byPriority(
  a: Pick<GraveSummary, 'priority' | 'purl'>,
  b: Pick<GraveSummary, 'priority' | 'purl'>,
): number {
  const pa = a.priority ?? Number.NEGATIVE_INFINITY;
  const pb = b.priority ?? Number.NEGATIVE_INFINITY;
  if (pa !== pb) return pb > pa ? 1 : -1;
  return a.purl < b.purl ? -1 : a.purl > b.purl ? 1 : 0;
}

/**
 * The rank and the size bucket of every grave of a scan, by `priority` (UI-GY-4, design 4.4). With N graves a grave at
 * 0-based rank r is in bucket min(3, floor(4r / N)). Graves with equal priority take the bucket of the first of the
 * tie, so equal urgency is never drawn at two sizes. A grave without a priority is in the smallest bucket.
 */
export function rankGraves(
  graves: readonly Pick<GraveSummary, 'purl' | 'priority'>[],
): Map<string, Rank> {
  const sorted = [...graves].sort(byPriority);
  const total = sorted.length;
  const out = new Map<string, Rank>();
  let tieStart = 0;
  sorted.forEach((g, i) => {
    if (i > 0 && sorted[i - 1]?.priority !== g.priority) tieStart = i;
    const bucket =
      g.priority === null ? 3 : (Math.min(3, Math.floor((4 * tieStart) / total)) as 0 | 1 | 2 | 3);
    if (!out.has(g.purl)) out.set(g.purl, { position: i + 1, total, bucket });
  });
  return out;
}
