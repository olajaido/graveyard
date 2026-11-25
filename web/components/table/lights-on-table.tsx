'use client';
import { AppLink } from '@/components/layout/app-link';
import { Pill } from '@/components/ui/pill';
import type { GraveSummary } from '@/lib/api/types';
import { causeOf } from '@/lib/model/cause';
import { displayOf, relationOf } from '@/lib/model/grave';
import { parseDisplayPurl } from '@/lib/model/purl';
import { defaultDir, graveHref, type SortDir, type SortKey } from '@/lib/model/route';
import { SortHeader } from './sort-header';
import { ROW_HEIGHT, useWindowRows } from './use-window-rows';

const COLUMNS = 7;

export function formatPriority(priority: number | null): string {
  return priority === null ? 'not recorded' : priority.toFixed(1);
}

/**
 * The register with the lights on (ui-core UI-TBL-1 to UI-TBL-5): the same graves as a real table on parchment, sorted
 * by package, state or priority. Graves arrive already filtered and sorted. A wide table scrolls inside a focusable,
 * named region, never the page. Past 500 rows only a window of rows is rendered.
 */
export function LightsOnTable({
  scanId,
  graves,
  sort,
  dir,
  onSort,
}: {
  scanId: string;
  graves: readonly GraveSummary[];
  sort: SortKey;
  dir: SortDir;
  onSort: (sort: SortKey, dir: SortDir) => void;
}) {
  const rows = useWindowRows(graves.length);
  const header = (label: string, column: SortKey) => (
    <SortHeader
      label={label}
      column={column}
      sort={sort}
      dir={dir}
      onSort={(next) =>
        onSort(next, next === sort ? (dir === 'asc' ? 'desc' : 'asc') : defaultDir(next))
      }
    />
  );
  const visible = graves.slice(rows.start, rows.end);
  const cell = `px-5 ${rows.windowed ? 'whitespace-nowrap' : ''} text-ink-soft`;
  return (
    <div
      role="region"
      aria-label="Register of graves"
      // The region scrolls sideways (and, when windowed, up and down), so a keyboard user must be able to focus it.
      tabIndex={0}
      onScroll={rows.windowed ? rows.onScroll : undefined}
      className={`surface-paper overflow-x-auto rounded-[14px] bg-parchment text-ink ${rows.windowed ? 'max-h-[70vh] overflow-y-auto' : ''}`}
    >
      <table
        className="w-full min-w-[860px] border-collapse text-sm"
        aria-rowcount={rows.windowed ? graves.length + 1 : undefined}
      >
        <caption className="px-5 pb-1.5 pt-[18px] text-left font-display text-2xl font-semibold text-ink">
          The register, with the lights on
        </caption>
        <thead>
          <tr
            className="border-b-2 border-paper-rule"
            aria-rowindex={rows.windowed ? 1 : undefined}
          >
            {header('Package', 'package')}
            {header('State', 'state')}
            {header('Priority', 'priority')}
            <th scope="col" className="px-5 py-3 text-left font-semibold">
              Cause
            </th>
            <th scope="col" className="px-5 py-3 text-left font-semibold">
              Relationship
            </th>
            <th scope="col" className="px-5 py-3 text-left font-semibold">
              Scope
            </th>
            <th scope="col" className="px-5 py-3 text-left font-semibold">
              Service
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.windowed && rows.padTop > 0 && (
            <tr aria-hidden="true" style={{ height: rows.padTop }}>
              <td colSpan={COLUMNS} />
            </tr>
          )}
          {visible.map((g, i) => {
            const display = displayOf(g);
            const p = parseDisplayPurl(g.purl);
            return (
              <tr
                key={g.purl}
                aria-rowindex={rows.windowed ? rows.start + i + 2 : undefined}
                style={rows.windowed ? { height: ROW_HEIGHT } : undefined}
                className="border-t border-paper-hair"
              >
                <th
                  scope="row"
                  className={`px-5 text-left font-normal ${rows.windowed ? 'whitespace-nowrap' : 'py-3'}`}
                >
                  <AppLink
                    href={graveHref(scanId, g.purl)}
                    className="font-mono text-ink underline underline-offset-2"
                  >
                    {p.fullName}@{p.version}
                  </AppLink>
                </th>
                <td className={cell}>
                  <Pill tone={display.type === 'unknown' ? 'neutral' : display.type}>
                    {display.label}
                  </Pill>
                </td>
                <td className={`${cell} tabular-nums`}>{formatPriority(g.priority)}</td>
                <td className={cell}>{causeOf(g) || '—'}</td>
                <td className={cell}>{relationOf(g).text}</td>
                <td className={cell}>{g.scope}</td>
                <td className={`${cell} font-mono text-ink-muted`}>{g.services.join(', ')}</td>
              </tr>
            );
          })}
          {rows.windowed && rows.padBottom > 0 && (
            <tr aria-hidden="true" style={{ height: rows.padBottom }}>
              <td colSpan={COLUMNS} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
