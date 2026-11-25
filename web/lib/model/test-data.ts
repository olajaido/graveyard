import type { GraveSummary } from '@/lib/api/types';

/** A grave for tests. Defaults: an Ailing, direct, runtime dependency in the root service. */
export function makeGrave(over: Partial<GraveSummary> = {}): GraveSummary {
  return {
    purl: 'pkg:npm/left-pad@1.3.0',
    state: 'ailing',
    deadReason: null,
    cursed: false,
    wounded: false,
    mortality: 50,
    confidence: 0.9,
    priority: 50,
    direct: true,
    scope: 'runtime',
    services: ['.'],
    pathCount: 1,
    via: null,
    ...over,
  };
}
