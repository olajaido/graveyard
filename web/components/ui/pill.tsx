import type { StateKey } from '@/lib/model/state-key';
import { PILL_CLASS } from './state-styles';

/** The text pill of a state on parchment (state ink on state pill). The text always says the state. */
export function Pill({ tone, children }: { tone: StateKey | 'neutral'; children: string }) {
  const colors = tone === 'neutral' ? 'bg-paper-hair text-ink-soft' : PILL_CLASS[tone];
  return (
    <span className={`inline-block rounded-pill px-2.5 py-0.5 text-[13px] font-semibold ${colors}`}>
      {children}
    </span>
  );
}
