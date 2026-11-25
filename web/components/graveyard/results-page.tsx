'use client';
import { useMemo, useRef } from 'react';
import { LightsOnTable } from '@/components/table/lights-on-table';
import { ErrorView } from '@/components/ui/error-view';
import { StatusRegion } from '@/components/ui/status-region';
import type { Client } from '@/lib/api/client';
import { getClient } from '@/lib/api/config';
import { copyForApiError } from '@/lib/api/errors';
import type { Scan } from '@/lib/api/types';
import { useFocusHeading, usePageTitle } from '@/lib/hooks/use-page';
import { useResource } from '@/lib/hooks/use-resource';
import { useViewState } from '@/lib/hooks/use-view-state';
import { rankGraves } from '@/lib/model/buckets';
import { filterGraves, sortGraves } from '@/lib/model/filter-sort';
import { buildPlots } from '@/lib/model/plots';
import { EmptyState } from './empty-state';
import { FilterChips } from './filter-chips';
import { Plot } from './plot';
import { Summary } from './summary';
import { ViewToggle } from './view-toggle';

const EMPTY_COUNTS = {
  total: 0,
  alive: 0,
  resting: 0,
  ailing: 0,
  dead: 0,
  cursed: 0,
  wounded: 0,
  unscored: 0,
};

/**
 * The results of a finished scan (ui-core section 7): the summary, the state chips, the view toggle, then the scene or
 * the Lights On table. The graves are read once, in pages of 200, and kept for the session.
 */
export function ResultsPage({ scan, client = getClient() }: { scan: Scan; client?: Client }) {
  const graves = useResource(
    `graves:${scan.scanId}`,
    (signal) => client.listGraves(scan.scanId, signal),
    () => true,
  );
  const heading = useRef<HTMLHeadingElement>(null);
  const { state, update } = useViewState();
  useFocusHeading(heading, graves.status === 'ready', 'complete');
  usePageTitle(`${scan.source.repo} · Graveyard`);

  const items = useMemo(() => (graves.status === 'ready' ? graves.data.items : []), [graves]);
  const ranks = useMemo(() => rankGraves(items), [items]);
  const plots = useMemo(
    () => buildPlots(scan.services, items, filterGraves(items, state.state)),
    [scan.services, items, state.state],
  );
  const rows = useMemo(
    () => sortGraves(filterGraves(items, state.state, state.service), state.sort, state.dir),
    [items, state.state, state.service, state.sort, state.dir],
  );

  if (graves.status === 'loading') {
    return (
      <div className="container-page py-16" role="status">
        <h1
          ref={heading}
          tabIndex={-1}
          className="m-0 font-display text-4xl font-semibold outline-none"
        >
          {scan.source.repo}
        </h1>
        <p className="text-bone-muted">Unearthing the graves…</p>
      </div>
    );
  }
  if (graves.status === 'error') {
    return (
      <ErrorView
        copy={copyForApiError(graves.error, 'scan')}
        onRetry={graves.reload}
        detail={scan.source.repo}
      />
    );
  }

  const counts = scan.counts ?? EMPTY_COUNTS;
  const serviceIds = plots.map((p) => p.id);
  return (
    <>
      <Summary
        scan={scan}
        counts={counts}
        plots={plots.length}
        graves={items}
        headingRef={heading}
      />
      {items.length === 0 ? (
        <div className="container-page pb-20">
          <EmptyState counts={counts} />
        </div>
      ) : (
        <div className="container-page flex flex-col gap-7 pb-20 pt-2">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <FilterChips
              value={state.state}
              onChange={(next) => update({ state: next })}
              counts={scan.counts}
              total={items.length}
            />
            <div className="flex flex-wrap items-center gap-3">
              {state.view === 'table' && serviceIds.length > 1 && (
                <label className="flex items-center gap-2 text-sm text-bone-muted">
                  Service
                  <select
                    value={state.service ?? ''}
                    onChange={(e) => update({ service: e.target.value || undefined })}
                    className="h-11 rounded-md border border-control-line bg-ground px-3 font-mono text-sm text-bone"
                  >
                    <option value="">All services</option>
                    {serviceIds.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <ViewToggle value={state.view} onChange={(view) => update({ view })} />
            </div>
          </div>

          {state.view === 'scene' ? (
            <div className="flex flex-col gap-9">
              {plots.map((plot) => (
                <Plot
                  key={plot.id}
                  plot={plot}
                  ranks={ranks}
                  scanId={scan.scanId}
                  filter={state.state}
                />
              ))}
              <p className="m-0 text-sm text-bone-quiet">
                Taller stones need you sooner, relative to this scan. The Lights on view lists the
                same graves as a table.
              </p>
            </div>
          ) : (
            <LightsOnTable
              scanId={scan.scanId}
              graves={rows}
              sort={state.sort}
              dir={state.dir}
              onSort={(sort, dir) => update({ sort, dir })}
            />
          )}
          {state.view === 'table' && rows.length === 0 && (
            <p className="m-0 text-bone-muted">
              No graves match this filter.{' '}
              <button
                type="button"
                onClick={() => update({ state: undefined, service: undefined })}
                className="cursor-pointer border-0 bg-transparent p-0 font-[inherit] text-bone underline"
              >
                Show all
              </button>
            </p>
          )}
        </div>
      )}
      <StatusRegion message="Exhumation complete" />
    </>
  );
}
