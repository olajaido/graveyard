import { ToeTagIcon } from '@/components/art/toe-tag-icon';
import { AppLink } from '@/components/layout/app-link';
import { INK_CLASS, INK_VAR } from '@/components/ui/state-styles';
import type { GraveSummary } from '@/lib/api/types';
import { byPriority } from '@/lib/model/buckets';
import { displayOf, relationOf } from '@/lib/model/grave';
import { parseDisplayPurl } from '@/lib/model/purl';
import { graveHref } from '@/lib/model/route';

export const DIG_FIRST_COUNT = 5;

/**
 * "Dig these first": the five graves with the highest priority, as toe tags (ui-core UI-GY-11). A tag shows the name and
 * version, the state in words, and how the package arrived. Nothing else: those are the facts of the graves list.
 */
export function DigFirst({ scanId, graves }: { scanId: string; graves: readonly GraveSummary[] }) {
  const top = [...graves].sort(byPriority).slice(0, DIG_FIRST_COUNT);
  if (top.length === 0) return null;
  return (
    <section aria-labelledby="dig-first-title" className="mt-4 flex flex-col gap-2.5">
      <h2 id="dig-first-title" className="m-0 font-display text-2xl font-semibold">
        Dig these first
      </h2>
      <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
        {top.map((g) => {
          const display = displayOf(g);
          const type = display.type === 'unknown' ? 'alive' : display.type;
          const p = parseDisplayPurl(g.purl);
          return (
            <li key={g.purl}>
              <AppLink
                href={graveHref(scanId, g.purl)}
                className="flex items-center gap-3.5 rounded-[6px_22px_22px_6px] bg-parchment py-2.5 pl-3 pr-[18px] text-ink no-underline"
              >
                <ToeTagIcon color={INK_VAR[type]} />
                <span className="min-w-0 flex-1 break-all font-mono text-sm">
                  {p.fullName}@{p.version}
                </span>
                <span className={`text-right text-[13px] font-semibold ${INK_CLASS[type]}`}>
                  {display.label} · {relationOf(g).text}
                </span>
              </AppLink>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
