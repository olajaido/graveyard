import { Pill } from '@/components/ui/pill';
import type { Certificate, GraveSummary } from '@/lib/api/types';
import { displayOf } from '@/lib/model/grave';
import { parseDisplayPurl, parsePackageKey } from '@/lib/model/purl';

/** The sentence under the line of descent (ui-core UI-CERT-3): who brought the package in, and how many paths lead here. */
export function descentSentence(
  c: Pick<Certificate, 'direct' | 'via' | 'pathCount' | 'examplePaths'>,
): string {
  const how = c.direct
    ? 'You chose this package yourself.'
    : c.via
      ? `It arrived with ${parseDisplayPurl(c.via).fullName}.`
      : c.examplePaths.length > 0
        ? 'It arrived as a transitive dependency.'
        : 'It is a transitive dependency. No path to it was kept.';
  const shown = c.examplePaths.length;
  if (c.pathCount > 1 && shown > 0) {
    return `${how} ${c.pathCount} paths lead here${shown < c.pathCount ? `, showing ${shown}` : ''}.`;
  }
  return how;
}

/**
 * The line of descent (ui-core UI-CERT-3): the service, then each package of each example path, ending at this package.
 * A package that is in the graves list the page already holds gets a state badge; one that is not gets none and costs
 * no request (design decision N6).
 */
export function Descent({
  certificate,
  repo,
  graves,
}: {
  certificate: Certificate;
  repo: string | null;
  graves: readonly GraveSummary[] | null;
}) {
  const byKey = new Map((graves ?? []).map((g) => [g.purl.toLowerCase(), g]));
  const { examplePaths } = certificate;
  return (
    <section aria-labelledby="descent-title" className="flex flex-col gap-3">
      <h2 id="descent-title" className="m-0 font-display text-2xl font-semibold">
        Line of descent
      </h2>
      {examplePaths.length === 0 ? (
        <p className="m-0 text-[15px] text-ink-soft">
          Not recorded. No path to this package was kept.
        </p>
      ) : (
        examplePaths.map((path, index) => (
          <ol
            key={`${path.service}:${index}`}
            aria-label={
              examplePaths.length > 1 ? `Path ${index + 1} of ${examplePaths.length}` : 'Path'
            }
            className="m-0 flex list-none flex-wrap items-center gap-2.5 p-0 font-mono text-sm"
          >
            <li className="rounded-sm border border-paper-rule px-3 py-1.5">
              {path.service === '.' && repo ? repo.split('/').pop() : path.service}
            </li>
            {path.nodes.map((key, i) => {
              const last = i === path.nodes.length - 1;
              const p = parsePackageKey(key);
              const known = byKey.get(`pkg:${key}`.toLowerCase());
              const display = known ? displayOf(known) : null;
              return (
                <li key={`${key}:${i}`} className="contents">
                  <span aria-hidden="true" className="text-ink-muted">
                    →
                  </span>
                  <span
                    className={`flex items-center gap-2 rounded-sm border px-3 py-1.5 ${
                      last ? 'border-ink-muted bg-paper-tint' : 'border-paper-rule'
                    }`}
                    aria-current={last ? 'true' : undefined}
                  >
                    {p.fullName}@{p.version}
                    {display && display.type !== 'unknown' && !last && (
                      <Pill tone={display.type}>{display.label}</Pill>
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
        ))
      )}
      <p className="m-0 text-[15px] text-ink-soft">{descentSentence(certificate)}</p>
    </section>
  );
}
