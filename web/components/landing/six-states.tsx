import { GraveIcon } from '@/components/art/grave-icon';
import { BRIGHT_CLASS } from '@/components/ui/state-styles';
import { STATE_TERMS, type StateKey } from '@/lib/model/state-key';

// Written for model v2 and the PRD definitions (decisions D4, D5): Dead is declared dead and nothing else; Cursed and
// Wounded are overlays on any state, not a kind of dead or of alive.
const STATES: { key: StateKey; text: string }[] = [
  { key: 'alive', text: 'Maintained and growing. Nothing to do.' },
  { key: 'resting', text: 'Finished, not abandoned. Quiet because it is done.' },
  { key: 'ailing', text: 'Cracks are showing. Worth watching.' },
  {
    key: 'dead',
    text: 'Declared dead on evidence: deprecated, archived or retired by its maintainer.',
  },
  { key: 'cursed', text: 'A known vulnerability with no fix, on any package. Dig these up first.' },
  {
    key: 'wounded',
    text: 'A fixable vulnerability, or an upgrade is advised, on any package. Upgrade, do not replace.',
  },
];

export function SixStates() {
  return (
    <section
      id="states"
      aria-labelledby="states-title"
      className="cv-auto scroll-mt-4 border-t border-hairline"
    >
      <div className="container-page flex flex-col gap-10 py-16 sm:py-[88px]">
        <h2
          id="states-title"
          className="m-0 font-display text-[clamp(36px,5vw,52px)] font-semibold leading-[1.1]"
        >
          Six states of being
        </h2>
        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] gap-4 p-0">
          {STATES.map((s) => (
            <li
              key={s.key}
              className="flex items-end gap-5 rounded-xl border border-surface-line bg-surface p-[22px]"
            >
              <GraveIcon type={s.key} className="shrink-0" />
              <div className="flex flex-col gap-1">
                <span className="font-semibold">
                  <span className={BRIGHT_CLASS[s.key]}>{STATE_TERMS[s.key].themed}</span>{' '}
                  <span className="font-normal text-bone-quiet">({STATE_TERMS[s.key].plain})</span>
                </span>
                <p className="m-0 text-[15px] text-bone-muted">{s.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
