import { describe, expect, it } from 'vitest';
import { formatDate, formatDateTime, sealDate, secondsBetween } from './dates';
import { FIRST_DELAY_MS, MAX_DELAY_MS, nextDelay } from './poll';

describe('nextDelay', () => {
  it('starts at 1.5 s, multiplies by 1.5 and stops at 5 s', () => {
    const delays = [FIRST_DELAY_MS];
    for (let i = 0; i < 5; i++) delays.push(nextDelay(delays.at(-1)!));
    expect(delays).toEqual([1500, 2250, 3375, 5000, 5000, 5000]);
    expect(MAX_DELAY_MS).toBe(5000);
  });
});

describe('dates', () => {
  it('formats in UTC', () => {
    expect(formatDate('2026-11-22T23:59:59Z')).toBe('22 Nov 2026');
    expect(formatDate('2026-09-03')).toBe('3 Sep 2026');
    expect(formatDateTime('2026-11-22T21:04:06.345440+00:00')).toBe('22 Nov 2026, 21:04 UTC');
  });
  it('gives nothing for a missing or bad date', () => {
    expect(formatDate(null)).toBe('');
    expect(formatDate('nope')).toBe('');
    expect(sealDate('nope')).toBe('');
  });
  it('writes the seal date in roman months', () => {
    expect(sealDate('2026-11-22')).toBe('22·XI·2026');
    expect(sealDate('2026-01-05')).toBe('5·I·2026');
    expect(sealDate('2026-12-31T10:00:00Z')).toBe('31·XII·2026');
  });
  it('never gives a negative duration', () => {
    const start = '2026-11-22T22:34:59Z';
    expect(secondsBetween(start, Date.parse(start) + 41_500)).toBe(41);
    expect(secondsBetween(start, Date.parse(start) - 10_000)).toBe(0);
    expect(secondsBetween('nope', 1)).toBe(0);
  });
});
