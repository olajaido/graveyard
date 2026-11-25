import evidence from '@/content/evidence.generated.json';

/**
 * The held-out result, from eval/heldout/results.v2.json through scripts/gen-evidence.mjs (ui-core UI-LAND-5). When
 * the formal verdict is not a pass the stone says so, as the mockup does.
 */
export function EvidenceStone() {
  const { deadPrecision: p, verdictPassed } = evidence;
  const all = p.num === p.den;
  return (
    <section
      id="evidence"
      aria-labelledby="evidence-title"
      className="cv-auto scroll-mt-4 border-t border-hairline bg-night-alt"
    >
      <div className="container-page flex flex-wrap items-center gap-14 py-16 sm:py-[88px]">
        <div className="mx-auto flex h-[380px] w-[300px] flex-none flex-col items-center justify-center gap-1.5 rounded-[150px_150px_10px_10px] border border-stone-line bg-stone shadow-[0_26px_0_-8px_var(--color-earth)]">
          <span className="text-xs uppercase tracking-[0.3em] text-stone-text">Here lie</span>
          <span className="font-display text-[104px] font-semibold leading-none text-bone">
            {p.num}/{p.den}
          </span>
          <span className="px-6 text-center font-display text-xl italic text-bone-muted">
            correctly pronounced dead
          </span>
          <span className="text-xs text-stone-text">
            95% interval {p.wilsonLow.toFixed(2)} – {p.wilsonHigh.toFixed(2)}
          </span>
        </div>
        <div className="flex min-w-0 flex-[1_1_420px] flex-col gap-5">
          <h2
            id="evidence-title"
            className="m-0 font-display text-[clamp(36px,5vw,52px)] font-semibold leading-[1.1]"
          >
            We don&apos;t guess at death
          </h2>
          <p className="m-0 text-lg text-bone-soft">
            The mortality model was frozen before we drew a fresh, held-out set to test it. On that
            set,{' '}
            {all
              ? 'every package it pronounced dead really was dead.'
              : `${p.num} of the ${p.den} packages it pronounced dead really were dead.`}
          </p>
          {!verdictPassed && (
            <p className="m-0 text-[15px] text-bone-quiet">
              The sample was small, so the formal verdict was inconclusive, and we say so on the
              stone.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
