import type { Certificate, Counts, ErrorCode, GraveSummary, Scan, Stage } from '@/lib/api/types';
import { hauntedGraves, hauntedScan } from './haunted-house';

/** A scan that is running in `stage`. `progress` is only kept for AUTOPSY, as the API does. */
export function runningScan(
  stage: Stage | null,
  progress: { examined: number; total: number } | null = null,
  over: Partial<Scan> = {},
): Scan {
  const queued = stage === 'QUEUED' || stage === null;
  return {
    ...hauntedScan,
    status: queued ? 'QUEUED' : 'RUNNING',
    stage,
    updatedAt: hauntedScan.createdAt,
    modelVersion: null,
    counts: null,
    partial: false,
    services:
      stage === 'QUEUED' || stage === 'VALIDATE' || stage === null ? null : hauntedScan.services,
    progress: stage === 'AUTOPSY' ? progress : null,
    error: null,
    ...over,
  };
}

export function failedScan(
  code: ErrorCode,
  stage: Stage = 'GRAPH',
  title = 'The scan failed.',
): Scan {
  return runningScan(stage, null, { status: 'FAILED', error: { code, title } });
}

export function completeScan(over: Partial<Scan> = {}): Scan {
  return { ...hauntedScan, ...over };
}

/** A scan stored before group B: no services, no progress. */
export function preBScan(): Scan {
  return { ...hauntedScan, services: null, progress: null };
}

export const EMPTY_COUNTS: Counts = {
  total: 12,
  alive: 12,
  resting: 0,
  ailing: 0,
  dead: 0,
  cursed: 0,
  wounded: 0,
  unscored: 0,
};

export function emptyScan(): Scan {
  return completeScan({
    counts: EMPTY_COUNTS,
    services: [{ id: '.', manifests: [{ ecosystem: 'npm', path: 'package-lock.json' }] }],
  });
}

export function partialScan(): Scan {
  return completeScan({ partial: true, counts: { ...hauntedScan.counts!, unscored: 7 } });
}

/** `n` graves in the root service with distinct purls and falling priority, for the window and the cap. */
export function manyGraves(n: number): GraveSummary[] {
  const states = ['dead', 'ailing', 'resting'] as const;
  return Array.from({ length: n }, (_, i) => ({
    purl: `pkg:npm/pkg-${String(i).padStart(4, '0')}@1.${i % 10}.0`,
    state: states[i % 3]!,
    deadReason: i % 3 === 0 ? ('declared' as const) : null,
    cursed: i % 97 === 0,
    wounded: i % 53 === 0,
    mortality: 90 - (i % 80),
    confidence: 0.9,
    priority: n - i,
    direct: i % 4 === 0,
    scope: i % 5 === 0 ? ('dev' as const) : ('runtime' as const),
    services: ['.'],
    pathCount: 1,
    via: i % 4 === 0 ? null : `pkg:npm/pkg-${String(Math.max(0, i - 1)).padStart(4, '0')}@1.0.0`,
  }));
}

/** The same graves as a scan from before group B (no `via`). */
export function withoutVia(graves: GraveSummary[]): GraveSummary[] {
  return graves.map((g) => ({ ...g, via: null }));
}

/** A certificate with every optional field empty, as an unscored or sparse node looks (UI-Q-7). */
export function minimalCertificate(g: GraveSummary): Certificate {
  return {
    ...g,
    servicesAffected: g.services.length,
    examplePaths: [],
    exposure: null,
    exposureAssumed: null,
    signals: null,
    evidence: null,
    contributions: null,
    normalisedRisks: null,
    warnings: [],
    repo: null,
    evidenceLinks: [],
    asOf: '2026-11-23',
    modelVersion: 'v2',
  };
}

export const ALL_HAUNTED_GRAVES = hauntedGraves.items;
