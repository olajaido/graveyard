import scan from '@/content/haunted-house/scan.json';
import { formatDate, secondsBetween } from '@/lib/model/dates';

/**
 * One real result, from the committed capture of a scan of olajaido/haunted-house (ui-core UI-LAND-5): every figure
 * and the date come from `content/haunted-house/scan.json`, none is typed here.
 */
export function ExampleStrip() {
  const { counts, source, createdAt, updatedAt } = scan;
  const seconds = secondsBetween(createdAt, Date.parse(updatedAt));
  return (
    <section aria-label="Example result" className="cv-auto bg-ground">
      <div className="container-page flex flex-wrap items-end justify-center gap-7 pb-24 pt-10">
        <div className="flex min-w-0 flex-[1_1_260px] flex-col gap-1.5 pb-4">
          <span className="font-mono text-sm text-bone-quiet">
            {source.repo}, exhumed in {seconds} seconds
          </span>
          <span className="font-display text-[96px] font-semibold leading-none">
            {counts.total}
          </span>
          <span className="text-bone-muted">
            dependencies dug up. This is what we found buried.
          </span>
          <span className="text-[13px] text-bone-quiet">
            A real scan of {formatDate(updatedAt)}.
          </span>
        </div>

        <div className="flex h-[220px] w-[170px] flex-col items-center justify-center gap-1 rounded-[85px_85px_8px_8px] border border-dead bg-stone shadow-[0_18px_0_-6px_var(--color-earth)]">
          <svg
            width="22"
            height="30"
            viewBox="0 0 22 30"
            fill="none"
            stroke="#E8887B"
            strokeWidth="2.5"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M11 2v26M3 10h16" />
          </svg>
          <span className="font-display text-[64px] font-semibold leading-none">{counts.dead}</span>
          <span className="eyebrow text-sm tracking-[0.14em] text-dead">Dead</span>
        </div>

        <div
          className="flex h-[250px] w-[130px] flex-col items-center justify-end gap-1 bg-cursed-body pb-7"
          style={{
            clipPath: 'polygon(50% 0, 72% 12%, 86% 100%, 14% 100%, 28% 12%)',
            filter: 'drop-shadow(0 0 22px rgba(196,174,245,0.45))',
          }}
        >
          <svg
            width="22"
            height="22"
            viewBox="0 0 16 16"
            fill="none"
            stroke="#C4AEF5"
            strokeWidth="1.6"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M8 1l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" />
          </svg>
          <span className="font-display text-[56px] font-semibold leading-none">
            {counts.cursed}
          </span>
          <span className="eyebrow text-sm tracking-[0.14em] text-cursed">Cursed</span>
        </div>

        <div className="relative flex h-[200px] w-[170px] -rotate-[4deg] flex-col items-center justify-center gap-1 rounded-[16px_16px_8px_8px] border border-ailing bg-stone">
          <svg
            aria-hidden="true"
            focusable="false"
            width="40"
            height="70"
            viewBox="0 0 40 70"
            className="absolute right-[26px] top-0"
          >
            <path d="M30 0 L18 22 L28 36 L14 66" fill="none" stroke="#E9B266" strokeWidth="1.6" />
          </svg>
          <span className="font-display text-[64px] font-semibold leading-none">
            {counts.ailing}
          </span>
          <span className="eyebrow text-sm tracking-[0.14em] text-ailing">Ailing</span>
        </div>
      </div>
    </section>
  );
}
