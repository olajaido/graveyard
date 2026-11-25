import type { KeyboardEvent } from 'react';
import { Grave } from '@/components/art/grave';
import { AppLink } from '@/components/layout/app-link';
import { BRIGHT_CLASS } from '@/components/ui/state-styles';
import type { GraveSummary } from '@/lib/api/types';
import { WIDTHS, type Rank } from '@/lib/model/buckets';
import { displayOf, relationOf } from '@/lib/model/grave';
import { parseDisplayPurl } from '@/lib/model/purl';
import { graveHref } from '@/lib/model/route';

/** The words under the stone: the version, `dev` for a dev dependency, and who brought it in. */
export function stoneMeta(g: GraveSummary): string {
  const version = parseDisplayPurl(g.purl).version ?? '';
  const relation = relationOf(g);
  return [version, g.scope === 'dev' ? 'dev' : '', relation.kind === 'direct' ? '' : relation.text]
    .filter(Boolean)
    .join(' · ');
}

/** The accessible name of a stone: "pycrypto 2.6.1, Dead and cursed, priority 1 of 7" (PRD GY-6). */
export function stoneLabel(g: GraveSummary, rank: Rank): string {
  const { name, version } = (({ fullName, version: v }) => ({ name: fullName, version: v ?? '' }))(
    parseDisplayPurl(g.purl),
  );
  return `${[name, version].filter(Boolean).join(' ')}, ${displayOf(g).words}, priority ${rank.position} of ${rank.total}`;
}

/**
 * One grave of a plot: a link to its certificate. The art is decorative; the link's name and the two lines of text carry
 * the facts, so the state is never colour alone. `tabIndex` is part of the plot's roving tabindex.
 */
export function Stone({
  grave,
  rank,
  scanId,
  tabIndex,
  onKeyDown,
  onFocus,
}: {
  grave: GraveSummary;
  rank: Rank;
  scanId: string;
  tabIndex: 0 | -1;
  onKeyDown: (event: KeyboardEvent<HTMLAnchorElement>) => void;
  onFocus: () => void;
}) {
  const display = displayOf(grave);
  const width = WIDTHS[rank.bucket];
  const type = display.type === 'unknown' ? 'alive' : display.type;
  return (
    <AppLink
      href={graveHref(scanId, grave.purl)}
      data-stone=""
      aria-label={stoneLabel(grave, rank)}
      tabIndex={tabIndex}
      onKeyDown={onKeyDown}
      onFocus={onFocus}
      className="gy-stone text-bone"
      style={{ width: width + 16 }}
    >
      <Grave type={type} width={width} />
      <span className="break-all text-center font-mono text-xs leading-[1.3]">
        {parseDisplayPurl(grave.purl).fullName}
      </span>
      <span className={`text-center text-[11px] leading-[1.3] ${BRIGHT_CLASS[type]}`}>
        {stoneMeta(grave)}
      </span>
    </AppLink>
  );
}
