'use client';
import { useEffect, useState } from 'react';
import { secondsBetween } from '@/lib/model/dates';

export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds} second${seconds === 1 ? '' : 's'}`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m} min ${s} s`;
}

/**
 * The time since the scan was created, ticking each second. It is not in the live region: a clock that speaks every
 * second is noise. The server and the browser clocks can differ, so the figure is never negative.
 */
export function Elapsed({ since, now = Date.now }: { since: string; now?: () => number }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  void tick;
  return <>{formatElapsed(secondsBetween(since, now()))}</>;
}
