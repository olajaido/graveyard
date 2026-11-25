'use client';
import { m, useReducedMotion } from 'framer-motion';
import { useId } from 'react';
import { PlotBackdrop } from '@/components/art/plot-backdrop';
import { AppLink } from '@/components/layout/app-link';
import type { GraveSummary } from '@/lib/api/types';
import { useRoving } from '@/lib/hooks/use-roving';
import type { Rank } from '@/lib/model/buckets';
import { restSentence, type Plot as PlotModel } from '@/lib/model/plots';
import { scanHref, type FilterKey } from '@/lib/model/route';
import { Stone } from './stone';

/**
 * One fenced plot (ui-core UI-GY-2, UI-GY-5, UI-GY-7): a service, its stones by attention class and priority (at most 24), and
 * one line about the rest with a link to the table. The stones are one tab stop; the arrow keys move between them.
 */
export function Plot({
  plot,
  ranks,
  scanId,
  filter,
}: {
  plot: PlotModel;
  ranks: Map<string, Rank>;
  scanId: string;
  filter: FilterKey | undefined;
}) {
  const titleId = useId();
  const reduce = useReducedMotion();
  const { groupRef, tabIndexFor, onKeyDown, setActive } = useRoving('[data-stone]');
  const count = plot.stones.length;
  return (
    <m.section
      aria-labelledby={titleId}
      initial={reduce ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="relative overflow-hidden rounded-2xl border border-hairline bg-night"
    >
      <div className="relative flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 px-[clamp(16px,5vw,26px)] pt-[22px]">
        <h2 id={titleId} className="m-0 font-display text-[32px] font-semibold">
          {plot.title}
        </h2>
        <span className="font-mono text-[13px] text-bone-quiet">{plot.subtitle}</span>
      </div>
      <div className="relative mt-[60px] bg-plot px-[clamp(16px,5vw,26px)] pb-[34px]">
        {/* The backdrop is hung from the top edge of this panel (its y = 200 is that edge), so the fence always stands
            on the panel, whatever height the title row has. The stones are one layer above it. */}
        <PlotBackdrop className="pointer-events-none absolute inset-x-0 -top-[200px] z-0 h-[260px] w-full" />
        <div
          ref={groupRef as React.RefObject<HTMLDivElement>}
          role="group"
          aria-label={`Graves of ${plot.title.toLowerCase()}`}
          className="relative z-10 flex min-h-[120px] flex-wrap items-end gap-x-[26px] gap-y-[30px]"
        >
          {plot.stones.map((grave: GraveSummary, i: number) => (
            <Stone
              key={`${plot.id}:${grave.purl}`}
              grave={grave}
              rank={ranks.get(grave.purl)!}
              scanId={scanId}
              tabIndex={tabIndexFor(i, count)}
              onKeyDown={(e) => onKeyDown(e, i)}
              onFocus={() => setActive(i)}
            />
          ))}
          {plot.clean && (
            <p className="m-0 pt-6 text-bone-quiet">Nothing buried here. This plot is clean.</p>
          )}
          {!plot.clean && plot.matching === 0 && (
            <p className="m-0 pt-6 text-bone-quiet">No graves in this plot match the filter.</p>
          )}
        </div>
        {plot.hidden > 0 && (
          <p className="relative z-10 m-0 pt-6 text-sm text-bone-muted">
            {restSentence(plot.rest)}
            {' — '}
            <AppLink
              href={scanHref(scanId, { view: 'table', service: plot.id, state: filter })}
              className="text-bone underline underline-offset-4"
            >
              see them in Lights on
              <span className="sr-only">{` (${plot.hidden} more graves of ${plot.title.toLowerCase()})`}</span>
            </AppLink>
          </p>
        )}
      </div>
    </m.section>
  );
}
