export const FIRST_DELAY_MS = 1500;
export const MAX_DELAY_MS = 5000;
export const MAX_FAILURES = 5;

/** The next polling delay: 1.5 s, then 1.5 times more each time, never above 5 s (UI-PRG-1). */
export function nextDelay(previous: number): number {
  return Math.min(MAX_DELAY_MS, Math.round(previous * 1.5));
}
