import type { Certificate, EvidenceKey } from '@/lib/api/types';
import { formatDate, formatDateTime } from '@/lib/model/dates';
import { linkLabel, safeLink } from '@/lib/model/links';
import { formatEvidenceValue, plainText, SIGNALS } from '@/lib/model/signals';

type Link = Certificate['evidenceLinks'][number];

/** Is the signal one that says the package is gone? (S1, S1b true.) It picks the wording of the registry link. */
function flagged(key: EvidenceKey, value: unknown): boolean {
  return (key === 's1_declared_death' || key === 's1b_version_deprecated') && value === true;
}

function LinkOut({ link, flag, about }: { link: Link; flag: boolean; about: string }) {
  const href = safeLink(link.url);
  if (!href) return null;
  return (
    <a
      href={href}
      rel="noopener noreferrer"
      target="_blank"
      className="text-paper-link underline underline-offset-2"
    >
      {linkLabel(link, flag)}
      <span className="sr-only">{` for ${about} (opens in a new tab)`}</span>
    </a>
  );
}

/** "Evidence on file" (ui-core UI-CERT-4): per signal its name, kind, value, fetch time, note and link-outs. No source text. */
export function EvidenceList({ certificate }: { certificate: Certificate }) {
  const { evidence, signals, evidenceLinks } = certificate;
  const advisories = signals?.s7_advisories ?? null;
  const asOf = formatDate(certificate.asOf) || null;
  return (
    <section aria-labelledby="evidence-title" className="flex flex-col gap-3">
      <h2 id="evidence-title" className="m-0 font-display text-2xl font-semibold">
        Evidence on file
      </h2>
      <ul className="m-0 flex list-none flex-col gap-3 p-0 text-[15px] text-ink-soft">
        {SIGNALS.map(({ key, name, kind }) => {
          const item = evidence?.[key] ?? null;
          const text = formatEvidenceValue(item?.value);
          const links = evidenceLinks.filter((l) => l.signals.includes(key));
          return (
            <li
              key={key}
              className="flex flex-col gap-0.5 border-b border-paper-line pb-3 last:border-b-0"
            >
              <span>
                <strong className="font-semibold text-ink">{name}</strong>{' '}
                <span className="text-ink-muted">({kind})</span>
              </span>
              <span>
                {text ?? 'Not recorded'}
                {item?.fetched_at && text !== null && (
                  <span className="text-ink-muted"> · read {formatDateTime(item.fetched_at)}</span>
                )}
              </span>
              {item?.note && (
                <span className="text-sm text-ink-muted">{plainText(item.note, asOf)}</span>
              )}
              {key === 's7_advisories' && advisories && advisories.length > 0 && (
                <ul className="m-0 mt-1 flex list-none flex-col gap-1 p-0">
                  {advisories.map((a) => {
                    const link = links.find(
                      (l) =>
                        l.kind === 'advisory' && l.url.endsWith(`/${encodeURIComponent(a.id)}`),
                    );
                    return (
                      <li key={a.id} className="flex flex-wrap items-baseline gap-x-3">
                        <span className="font-mono text-sm text-ink">{a.id}</span>
                        <span className="font-semibold">
                          {a.has_fix ? 'fix available' : 'no fix'}
                        </span>
                        <span className="text-ink-muted">
                          {a.published_at
                            ? `published ${a.published_at}`
                            : 'publication date not recorded'}
                        </span>
                        {link && <LinkOut link={link} flag={false} about={`advisory ${a.id}`} />}
                      </li>
                    );
                  })}
                </ul>
              )}
              {key !== 's7_advisories' && links.length > 0 && (
                <span className="flex flex-wrap gap-x-4">
                  {links.map((l) => (
                    <LinkOut key={l.url} link={l} flag={flagged(key, item?.value)} about={name} />
                  ))}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** "Notes on the evidence" (UI-CERT-6): the warnings of the sources, with the signals they affected. */
export function EvidenceNotes({
  warnings,
  asOf = null,
}: {
  warnings: Certificate['warnings'];
  asOf?: string | null;
}) {
  if (warnings.length === 0) return null;
  return (
    <section aria-labelledby="notes-title" className="flex flex-col gap-3">
      <h2 id="notes-title" className="m-0 font-display text-2xl font-semibold">
        Notes on the evidence
      </h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[15px] text-ink-soft">
        {warnings.map((w, i) => (
          <li key={`${w.code}:${w.source}:${i}`}>
            <span className="font-mono text-sm text-ink">{plainText(w.source)}</span>:{' '}
            {plainText(w.detail, asOf)}
            {w.signals.length > 0 && (
              <span className="text-ink-muted">
                {' '}
                (affects {w.signals.map((k) => plainText(k)).join(', ')})
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
