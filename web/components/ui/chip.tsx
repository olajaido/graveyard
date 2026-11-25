import type { StateKey } from '@/lib/model/state-key';
import { DOT_CLASS } from './state-styles';

/** A toggle chip of the filter bar: `aria-pressed`, a state dot, a label and a count. */
export function Chip({
  pressed,
  onToggle,
  state,
  children,
  count,
}: {
  pressed: boolean;
  onToggle: () => void;
  state?: StateKey;
  children: string;
  count?: number;
}) {
  const tone = pressed
    ? 'bg-bone text-on-bone border-bone'
    : 'bg-surface text-bone border-surface-line hover:border-bone-quiet';
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={count === undefined ? undefined : `${children}, ${count}`}
      onClick={onToggle}
      className={`inline-flex h-11 cursor-pointer items-center gap-2 rounded-pill border px-4 text-sm font-medium ${tone}`}
    >
      {state && (
        <span
          aria-hidden="true"
          className={`inline-block size-2 rounded-full ${DOT_CLASS[state]}`}
        />
      )}
      {children}
      {count !== undefined && (
        <span className={pressed ? 'font-normal text-ink-soft' : 'font-normal text-bone-quiet'}>
          {count}
        </span>
      )}
    </button>
  );
}
