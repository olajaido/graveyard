'use client';
import { useRef, useState } from 'react';
import { OpenGraveScene } from '@/components/art/open-grave-scene';
import { StatusRegion } from '@/components/ui/status-region';
import type { Scan } from '@/lib/api/types';
import { useFocusHeading } from '@/lib/hooks/use-page';
import { clampProgress, lanternsFor } from '@/lib/model/stage-map';
import { Elapsed } from './elapsed';
import { LanternPath } from './lantern-path';

/** The announcement of the status region: the stage, and the examined count, but only when a tenth more is done. */
function announcement(scan: Scan, text: string): { key: string; text: string } {
  const progress = scan.stage === 'AUTOPSY' ? clampProgress(scan.progress) : null;
  if (!progress || progress.total === 0) return { key: `${scan.stage}`, text };
  const tenth = Math.floor((progress.examined / progress.total) * 10);
  return {
    key: `${scan.stage}:${tenth}`,
    text: `${text}: ${progress.examined} of ${progress.total} examined`,
  };
}

/**
 * The content of the page of a scan that is still running (ui-core UI-PRG-3 to UI-PRG-4): the open grave, the lantern path and the
 * numbers the API returns, nothing else. The page (`ScanPage`) supplies the header and the `<main>`. There is no running tally and no list of packages; those are not in the API
 * until the scan is complete.
 */
export function ExhumationView({ scan }: { scan: Scan }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useFocusHeading(heading, true);
  const view = lanternsFor(scan);
  const progress = scan.stage === 'AUTOPSY' ? clampProgress(scan.progress) : null;
  const plots = scan.services ? new Set(scan.services.map((s) => s.id)).size : null;

  // The status region changes on a new stage or a new tenth, not on every poll (derived state, set during render).
  const next = announcement(scan, view.text);
  const [announced, setAnnounced] = useState(next);
  if (announced.key !== next.key) setAnnounced(next);

  return (
    <>
      <section aria-label="Exhumation in progress" className="relative overflow-hidden bg-night">
        <div className="container-page relative z-[1] flex flex-col gap-2 pt-6">
          <p className="eyebrow m-0 flex items-center gap-2.5 text-ailing">
            <span
              aria-hidden="true"
              className="gy-flame inline-block size-2 rounded-full bg-ailing"
            />
            Digging now · <Elapsed since={scan.createdAt} />
          </p>
          <h1
            ref={heading}
            tabIndex={-1}
            className="m-0 break-words font-display text-[clamp(36px,5vw,60px)] font-semibold leading-[1.05] outline-none [overflow-wrap:anywhere]"
          >
            {scan.source.repo}
          </h1>
          <p className="m-0 text-bone-soft">
            {plots !== null && `${plots} ${plots === 1 ? 'plot' : 'plots'} found. `}
            You can leave: the digging carries on without you.
          </p>
        </div>
        <OpenGraveScene depth={view.depth} className="-mt-10 block h-[420px] w-full" />
      </section>
      <div className="container-page flex flex-col gap-12 pb-20 pt-10">
        <section aria-labelledby="lantern-title" className="flex flex-col gap-3">
          <h2 id="lantern-title" className="m-0 font-display text-[30px] font-semibold">
            The lantern path
          </h2>
          <LanternPath statuses={view.statuses} services={scan.services} progress={progress} />
        </section>
        <p className="m-0 text-sm text-bone-quiet">
          Counts by state appear when the last lantern is lit. Until then only the steps and the
          number of packages examined are known.
        </p>
      </div>
      <StatusRegion message={announced.text} />
    </>
  );
}
