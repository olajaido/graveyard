'use client';
import { m, useReducedMotion } from 'framer-motion';
import { useRef, type ReactNode } from 'react';
import { BrandMark } from '@/components/art/brand-mark';
import { WaxSeal, type SealTone } from '@/components/art/wax-seal';
import { INK_CLASS } from '@/components/ui/state-styles';
import type { Certificate, GraveSummary } from '@/lib/api/types';
import { useFocusHeading, usePageTitle } from '@/lib/hooks/use-page';
import { causeOfDeath } from '@/lib/model/cause';
import { formatDate, sealDate } from '@/lib/model/dates';
import { displayOf } from '@/lib/model/grave';
import { parseDisplayPurl } from '@/lib/model/purl';
import { Descent } from './descent';
import { EvidenceList, EvidenceNotes } from './evidence-list';

const SEAL_WORD: Partial<Record<SealTone, string>> = {
  dead: 'DECEASED',
  cursed: 'CURSED',
  ailing: 'AILING',
  resting: 'RESTING',
  wounded: 'WOUNDED',
  alive: 'ALIVE',
};

function Field({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      className={`flex flex-col gap-0.5 border-b border-paper-line pb-2.5 ${wide ? 'sm:col-span-2' : ''}`}
    >
      <dt className="text-xs uppercase tracking-[0.14em] text-ink-muted">{label}</dt>
      <dd className="m-0 text-[17px]">{children}</dd>
    </div>
  );
}

const NOT_RECORDED = <span className="text-ink-muted">Not recorded</span>;

/**
 * The Death Certificate (ui-core section 9): the fields of the payload on parchment, the line of descent, the evidence
 * with its link-outs, the notes, the seal. A field the API returns as empty reads "Not recorded". A field the API
 * does not return at all ("Born", the "Buried alongside" panel, the "rites" panel of the mockup) is not drawn: no
 * placeholder, no promise of a later release.
 */
export function CertificateView({
  certificate: c,
  scanId,
  repo,
  graves,
}: {
  certificate: Certificate;
  scanId: string;
  repo: string | null;
  graves: readonly GraveSummary[] | null;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const reduce = useReducedMotion();
  const p = parseDisplayPurl(c.purl);
  const display = displayOf(c);
  const dead = display.base === 'dead';
  usePageTitle(`${p.fullName}${p.version ? `@${p.version}` : ''} · Graveyard`);
  useFocusHeading(heading, true);

  const tone: SealTone | null = display.type === 'unknown' ? null : display.type;
  const ink = display.type === 'unknown' ? 'text-ink' : INK_CLASS[display.type];
  const latestRelease = c.signals?.s2_latest_release_at ?? null;

  return (
    <article
      aria-label={dead ? 'Certificate of death' : 'Certificate of condition'}
      className="surface-paper mx-auto flex min-w-0 max-w-[880px] flex-[1_1_640px] flex-col gap-8 rounded-sm border border-paper-hair bg-parchment px-[clamp(24px,5vw,64px)] py-14 text-ink shadow-[0_30px_80px_rgba(0,0,0,0.45)]"
    >
      <div className="flex flex-col items-center gap-2.5 border-b border-double border-paper-rule-strong pb-7 text-center">
        <BrandMark width={34} height={40} strokeWidth={1.5} />
        <p className="m-0 text-xs uppercase tracking-[0.3em] text-ink-muted">
          Registry of the Graveyard
        </p>
        <h1
          ref={heading}
          tabIndex={-1}
          className="m-0 font-display text-[clamp(40px,5vw,58px)] font-bold leading-[1.05] outline-none"
        >
          {dead ? 'Certificate of Death' : 'Certificate of Condition'}
        </h1>
        <p className="m-0 font-display text-xl italic text-ink-soft">
          issued on the evidence, {formatDate(c.asOf) || 'date not recorded'}
        </p>
      </div>

      <dl className="m-0 grid grid-cols-1 gap-x-10 gap-y-6 sm:grid-cols-2">
        <Field label={dead ? 'Name of the deceased' : 'Package'} wide>
          <span className="font-mono text-[26px] font-medium [overflow-wrap:anywhere]">
            {p.fullName}
            {p.version && <span className="text-ink-muted">@{p.version}</span>}
          </span>
        </Field>
        <Field label="Pronounced">
          <span className={`text-lg font-semibold ${ink}`}>
            {display.words.split(' and ')[0]}
            {display.base === 'dead' && c.deadReason ? ` · ${c.deadReason}` : ''}
          </span>
        </Field>
        <Field label="Complications">
          <span className={`text-lg font-semibold ${display.overlays.length ? ink : ''}`}>
            {display.overlays[0] === 'cursed'
              ? 'Cursed · known vulnerability, no fix'
              : display.overlays[0] === 'wounded'
                ? 'Wounded · upgrade advised'
                : 'None'}
          </span>
        </Field>
        <Field label="Cause of death" wide>
          <span className="font-display text-2xl leading-[1.35]">{causeOfDeath(c)}</span>
        </Field>
        <Field label="Ecosystem">{p.ecosystemLabel}</Field>
        <Field label="Place of rest">
          service{c.services.length === 1 ? '' : 's'}{' '}
          <span className="font-mono">{c.services.map((s) => `"${s}"`).join(', ')}</span>, {c.scope}{' '}
          scope
        </Field>
        <Field label="Mortality">
          {c.mortality === null ? (
            NOT_RECORDED
          ) : (
            <>
              {Math.round(c.mortality)} <span className="text-ink-muted">/ 100</span>
            </>
          )}
        </Field>
        <Field label="Confidence">
          {c.confidence === null ? NOT_RECORDED : c.confidence.toFixed(1)}
          {c.priority !== null && (
            <span className="text-ink-muted"> · priority {c.priority.toFixed(1)}</span>
          )}
        </Field>
        <Field label="Last released">
          {latestRelease ? formatDate(latestRelease) : NOT_RECORDED}
        </Field>
      </dl>

      <Descent certificate={c} repo={repo} graves={graves} />
      <EvidenceList certificate={c} />
      <EvidenceNotes warnings={c.warnings} asOf={formatDate(c.asOf) || null} />

      <div className="flex flex-wrap items-end justify-between gap-4 border-t border-double border-paper-rule-strong pt-5">
        <span className="font-mono text-xs text-ink-muted">
          scan {scanId} · model {c.modelVersion}
        </span>
        <div className="flex items-center gap-[18px]">
          <span className="font-display text-[22px] italic text-ink-soft">— the Coroner</span>
          {tone && (
            <m.div
              initial={reduce ? false : { opacity: 0, scale: 1.15 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.4 }}
            >
              <WaxSeal word={SEAL_WORD[tone] ?? ''} date={sealDate(c.asOf)} tone={tone} />
            </m.div>
          )}
        </div>
      </div>
    </article>
  );
}
