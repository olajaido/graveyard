import type { Progress, Scan } from '@/lib/api/types';

export const LANTERNS = [
  'Validate',
  'Exhume',
  'Identify',
  'Trace roots',
  'Autopsy',
  'Pronounce',
] as const;
export type LanternStatus = 'done' | 'working' | 'waiting' | 'stopped';

/** The index of the lantern that works in each stage the backend writes (design 6.2). */
const STAGE_LANTERN: Record<string, number> = {
  VALIDATE: 0,
  FETCH: 1,
  SBOM: 2,
  GRAPH: 3,
  AUTOPSY: 4,
  CLASSIFY: 5,
};

const STAGE_TEXT: Record<string, string> = {
  QUEUED: 'Waiting for a gravedigger',
  VALIDATE: 'Checking the plot',
  FETCH: 'Digging up the lockfiles',
  SBOM: 'Tagging the bodies',
  GRAPH: 'Tracing the roots',
  AUTOPSY: 'Examining the bodies',
  CLASSIFY: 'Pronouncing',
};

export interface LanternView {
  /** The status of each of the six lanterns, in order. */
  statuses: LanternStatus[];
  /** The line for the status region and the header. */
  text: string;
  /** False for a stage this version does not know: the caller keeps what it showed before and `text` is "Working…". */
  known: boolean;
  /** The dig depth, 0 to 1, for the open grave scene. */
  depth: number;
}

export function clampProgress(p: Progress | null | undefined): Progress | null {
  if (!p || p.total < 0 || p.examined < 0) return null;
  return { examined: Math.min(p.examined, p.total), total: p.total };
}

/** The lantern path of a scan, from its `status` and `stage` only (UI-PRG-2). */
export function lanternsFor(scan: Pick<Scan, 'status' | 'stage' | 'progress'>): LanternView {
  const waiting = LANTERNS.map((): LanternStatus => 'waiting');
  if (scan.status === 'COMPLETE') {
    return {
      statuses: LANTERNS.map((): LanternStatus => 'done'),
      text: 'Exhumation complete',
      known: true,
      depth: 1,
    };
  }
  const stage = scan.stage ?? 'QUEUED';
  const index = STAGE_LANTERN[stage];
  if (stage === 'DONE' && scan.status !== 'FAILED') {
    return {
      statuses: LANTERNS.map((): LanternStatus => 'done'),
      text: 'Exhumation complete',
      known: true,
      depth: 1,
    };
  }
  if (index === undefined) {
    const queued = stage === 'QUEUED';
    return {
      statuses: waiting,
      text: queued ? STAGE_TEXT.QUEUED! : 'Working…',
      known: queued,
      depth: 0,
    };
  }
  const failed = scan.status === 'FAILED';
  const statuses = LANTERNS.map((_, i): LanternStatus =>
    i < index ? 'done' : i === index ? (failed ? 'stopped' : 'working') : 'waiting',
  );
  const progress = stage === 'AUTOPSY' && !failed ? clampProgress(scan.progress) : null;
  const fraction = progress && progress.total > 0 ? progress.examined / progress.total : 0;
  return {
    statuses,
    text: STAGE_TEXT[stage] ?? 'Working…',
    known: true,
    depth: Math.min(1, Math.max(0, (index + fraction) / LANTERNS.length)),
  };
}
