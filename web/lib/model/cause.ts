import type { Certificate, GraveSummary } from '@/lib/api/types';
import { displayOf } from './grave';

type Causal = Pick<GraveSummary, 'state' | 'deadReason' | 'cursed' | 'wounded'>;

/** The risk ids of `contributions`, with the PRD 7.1 names. */
export const RISK_NAMES: Record<string, string> = {
  r2: 'release staleness',
  r3: 'commit staleness',
  r4: 'maintenance activity',
  r5: 'bus factor',
  r6: 'issue neglect',
  r8: 'Scorecard overall',
};

/** The Cause column of the table: from `state`, `deadReason` and the overlays only (design 4.5). */
export function causeOf(g: Causal): string {
  const parts: string[] = [];
  const base = displayOf(g).base;
  if (base === 'dead')
    parts.push(g.deadReason === 'score' ? 'High abandonment score' : 'Declared dead by its source');
  else if (base === 'ailing') parts.push('Signs of neglect');
  else if (base === 'resting') parts.push('Finished and stable');
  if (g.cursed) parts.push('Known vulnerability, no fix available');
  else if (g.wounded) parts.push('Upgrade advised');
  return parts.join('; ');
}

/**
 * The risk with the largest non-null contribution, or null when there is none. Ties go to the first id in order.
 */
export function largestContribution(
  contributions: Certificate['contributions'],
): { id: string; name: string; value: number } | null {
  if (!contributions) return null;
  let best: { id: string; value: number } | null = null;
  for (const id of Object.keys(contributions).sort()) {
    const value = contributions[id];
    if (typeof value === 'number' && value > 0 && (best === null || value > best.value))
      best = { id, value };
  }
  return best && { ...best, name: RISK_NAMES[best.id] ?? best.id };
}

/** The "Cause of death" of a certificate: a fixed template over the payload (UI-CERT-2). Never generated text. */
export function causeOfDeath(
  c: Pick<Certificate, 'state' | 'deadReason' | 'cursed' | 'wounded' | 'contributions'>,
): string {
  const base = displayOf(c).base;
  const sentences: string[] = [];
  if (base === 'dead') {
    sentences.push(
      c.deadReason === 'score'
        ? 'Pronounced dead on its abandonment score.'
        : 'Declared dead: its source reports it as deprecated, archived or retired.',
    );
  } else if (base === 'ailing') {
    sentences.push('Declining maintenance signals. It is not declared dead.');
  } else if (base === 'resting') {
    sentences.push('Quiet, and no risk indicators. Finished, not abandoned.');
  } else if (base === 'alive') {
    sentences.push('Maintained.');
  } else {
    sentences.push('No verdict: there are no scored signals for this version.');
  }
  if (c.cursed)
    sentences.push('A known vulnerability affects this version and no fixed version exists.');
  else if (c.wounded)
    sentences.push(
      'Upgrade advised: a fixed version exists, a fix is pending, or this version is deprecated.',
    );
  const main = base === 'unknown' ? null : largestContribution(c.contributions);
  if (main && base !== 'alive') sentences.push(`Largest contribution to its score: ${main.name}.`);
  return sentences.join(' ');
}
