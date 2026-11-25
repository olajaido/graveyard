import { Chip } from '@/components/ui/chip';
import type { Counts } from '@/lib/api/types';
import { FILTER_KEYS, type FilterKey } from '@/lib/model/route';
import { STATE_TERMS } from '@/lib/model/state-key';

/**
 * The state chips (ui-core UI-GY-8): All, Dead, Cursed, Ailing, Resting, Wounded, as toggle buttons. One is pressed at
 * a time. Each count is the API's own; "All" is the number of graves listed.
 */
export function FilterChips({
  value,
  onChange,
  counts,
  total,
}: {
  value: FilterKey | undefined;
  onChange: (next: FilterKey | undefined) => void;
  counts: Counts | null;
  total: number;
}) {
  const order: FilterKey[] = ['dead', 'cursed', 'ailing', 'resting', 'wounded'];
  const known = new Set<string>(FILTER_KEYS);
  return (
    <div role="group" aria-label="Filter by state" className="flex flex-wrap gap-2">
      <Chip pressed={value === undefined} onToggle={() => onChange(undefined)} count={total}>
        All
      </Chip>
      {order
        .filter((key) => known.has(key))
        .map((key) => (
          <Chip
            key={key}
            state={key}
            pressed={value === key}
            onToggle={() => onChange(value === key ? undefined : key)}
            count={counts ? counts[key] : undefined}
          >
            {STATE_TERMS[key].themed}
          </Chip>
        ))}
    </div>
  );
}
