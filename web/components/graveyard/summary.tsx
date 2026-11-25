import type { RefObject } from 'react';
import { GraveyardSky, SkyObjects } from '@/components/art/graveyard-sky';
import type { Counts, GraveSummary, Scan } from '@/lib/api/types';
import { formatDate } from '@/lib/model/dates';
import { DigFirst } from './dig-first';

/** "208 dependencies dug up across 2 plots. 17 dead, 2 cursed, 84 ailing." A count of zero is left out. */
export function summarySentence(counts: Counts, plots: number): string {
  const parts = [
    counts.dead > 0 ? `${counts.dead} dead` : '',
    counts.cursed > 0 ? `${counts.cursed} cursed` : '',
    counts.ailing > 0 ? `${counts.ailing} ailing` : '',
  ].filter(Boolean);
  const dug = `${counts.total} ${counts.total === 1 ? 'dependency' : 'dependencies'} dug up across ${plots} ${plots === 1 ? 'plot' : 'plots'}.`;
  return parts.length ? `${dug} ${parts.join(', ')}.` : dug;
}

/** The results header (ui-core UI-GY-1): repo, date, one sentence, the living and the resting, the fog banner. */
export function Summary({
  scan,
  counts,
  plots,
  graves,
  headingRef,
}: {
  scan: Scan;
  counts: Counts;
  plots: number;
  graves: readonly GraveSummary[];
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  return (
    <section aria-label="Scan summary" className="relative isolate overflow-hidden bg-night">
      {/* The art is one layer behind the text (z-0, the text is z-10). The moon and stars start to the right of the
          620px text column and are left out on narrow screens, where the text takes the whole width. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-0">
        <GraveyardSky className="absolute inset-0 h-full w-full" />
        <div
          data-testid="sky-objects"
          className="absolute inset-y-0 right-0 hidden md:block"
          style={{ left: 'max(680px, 52%)' }}
        >
          <SkyObjects className="h-[300px] w-full" />
        </div>
      </div>
      <div className="container-page relative z-10 flex flex-col gap-2 pb-[110px] pt-8">
        <p className="eyebrow m-0 text-alive">Exhumation complete · {formatDate(scan.updatedAt)}</p>
        <h1
          ref={headingRef}
          tabIndex={-1}
          className="m-0 font-display text-[clamp(36px,5vw,60px)] font-semibold leading-[1.05] outline-none [overflow-wrap:anywhere]"
        >
          {scan.source.repo}
        </h1>
        <p className="m-0 max-w-[620px] text-bone-soft">{summarySentence(counts, plots)}</p>
        <p className="m-0 text-bone-muted">
          The living: {counts.alive} · Resting: {counts.resting}
        </p>
        {(scan.partial || counts.unscored > 0) && (
          <p
            role="note"
            className="m-0 max-w-[620px] rounded-md border border-resting/50 bg-night-alt/90 px-3 py-2 text-sm text-bone"
          >
            {counts.unscored > 0
              ? `${counts.unscored} ${counts.unscored === 1 ? 'package' : 'packages'} could not be examined, so this picture is partial.`
              : 'Some packages could not be examined, so this picture is partial.'}
          </p>
        )}
        <DigFirst scanId={scan.scanId} graves={graves} />
      </div>
    </section>
  );
}
