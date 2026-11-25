import type { GraveSummary } from '@/lib/api/types';
import { parseDisplayPurl } from './purl';
import type { StateKey } from './state-key';

export type GraveType = StateKey | 'unknown';
export type BaseState = 'alive' | 'resting' | 'ailing' | 'dead' | 'unknown';
export type Overlay = 'cursed' | 'wounded';

export interface Display {
  /** Which grave to draw (frontend-design.md section 5). `unknown` draws none. */
  type: GraveType;
  base: BaseState;
  overlays: Overlay[];
  /** `dead · cursed`, `alive · wounded`, `resting`. */
  label: string;
  /** `Dead and cursed`, for accessible names. */
  words: string;
}

type Stated = Pick<GraveSummary, 'state' | 'cursed' | 'wounded'>;

function baseOf(state: string): BaseState {
  return state === 'alive' || state === 'resting' || state === 'ailing' || state === 'dead'
    ? state
    : 'unknown';
}

/**
 * The display state of a node, from the base state and the two overlays (PRD 7.4). If both overlays are true the UI
 * shows Cursed only. The grave is Cursed, else Dead or Ailing, else Wounded, else Resting or Alive.
 */
export function displayOf(g: Stated): Display {
  const base = baseOf(g.state);
  const overlays: Overlay[] = g.cursed ? ['cursed'] : g.wounded ? ['wounded'] : [];
  let type: GraveType;
  if (g.cursed) type = 'cursed';
  else if (base === 'dead' || base === 'ailing') type = base;
  else if (g.wounded) type = 'wounded';
  else type = base === 'unknown' ? 'unknown' : base;
  const label = [base, ...overlays].join(' · ');
  const words = [base, ...overlays]
    .map((w, i) => (i === 0 ? w[0]?.toUpperCase() + w.slice(1) : w))
    .join(' and ');
  return { type, base, overlays, label, words };
}

const SEVERITY: Record<GraveType, number> = {
  cursed: 0,
  dead: 1,
  ailing: 2,
  resting: 3,
  wounded: 4,
  alive: 5,
  unknown: 6,
};

/** Sort order of the State column. */
export function severityRank(g: Stated): number {
  return SEVERITY[displayOf(g).type];
}

export interface Relation {
  kind: 'direct' | 'via' | 'transitive';
  text: string;
  /** The introducer's name, for `via`. */
  via?: string;
}

/** How a package reached the project: direct, via another package, or transitive when no introducer was kept. */
export function relationOf(g: Pick<GraveSummary, 'direct' | 'via'>): Relation {
  if (g.direct) return { kind: 'direct', text: 'direct' };
  if (g.via) {
    const name = parseDisplayPurl(g.via).fullName;
    return { kind: 'via', text: `via ${name}`, via: name };
  }
  return { kind: 'transitive', text: 'transitive' };
}

/** `name` and `version` of a node, for display and for sorting. */
export function nameOf(g: Pick<GraveSummary, 'purl'>): { name: string; version: string } {
  const p = parseDisplayPurl(g.purl);
  return { name: p.fullName, version: p.version ?? '' };
}
