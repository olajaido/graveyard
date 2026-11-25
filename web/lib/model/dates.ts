const DAY = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
});
const TIME = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
});
const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII'];

function parse(iso: string): Date | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** `22 Nov 2026`, in UTC. Empty text when the input is not a date. */
export function formatDate(iso: string | null | undefined): string {
  const date = iso ? parse(iso) : null;
  return date ? DAY.format(date).replace('Sept', 'Sep') : '';
}

/** `22 Nov 2026, 21:04 UTC`. */
export function formatDateTime(iso: string | null | undefined): string {
  const date = iso ? parse(iso) : null;
  return date ? `${TIME.format(date).replace('Sept', 'Sep')} UTC` : '';
}

/** The date on the wax seal: `22·XI·2026`. */
export function sealDate(iso: string | null | undefined): string {
  const date = iso ? parse(iso) : null;
  return date ? `${date.getUTCDate()}·${ROMAN[date.getUTCMonth()]}·${date.getUTCFullYear()}` : '';
}

/** Whole seconds from `from` to `to`, never negative (the server and the browser clocks can differ). */
export function secondsBetween(from: string, to: number): number {
  const start = parse(from);
  return start ? Math.max(0, Math.floor((to - start.getTime()) / 1000)) : 0;
}
