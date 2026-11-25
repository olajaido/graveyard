import { GraveIcon } from '@/components/art/grave-icon';
import type { Counts } from '@/lib/api/types';

/** No graves at all (PRD GY-9). The counts say how many packages were examined. */
export function EmptyState({ counts }: { counts: Counts }) {
  return (
    <section aria-labelledby="empty-title" className="flex flex-col items-start gap-4 py-10">
      <GraveIcon type="alive" />
      <h2 id="empty-title" className="m-0 font-display text-[30px] font-semibold">
        No graves here. Your dependencies live.
      </h2>
      <p className="m-0 text-bone-muted">
        {counts.total} {counts.total === 1 ? 'package was' : 'packages were'} examined. The living:{' '}
        {counts.alive} · Resting: {counts.resting}.
      </p>
    </section>
  );
}
