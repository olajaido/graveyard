import type { EvidenceKey } from '@/lib/api/types';

/** The signals of the evidence, in the order of the certificate, with plain names (PRD 7.1). */
export const SIGNALS: readonly { key: EvidenceKey; name: string; kind: string }[] = [
  { key: 's1_declared_death', name: 'Declared dead', kind: 'Registry or repository status' },
  { key: 's1b_version_deprecated', name: 'This version deprecated', kind: 'Registry status' },
  { key: 's2_latest_release_at', name: 'Latest release', kind: 'Release history' },
  { key: 's3_last_push_at', name: 'Last push to the repository', kind: 'Repository activity' },
  { key: 's4_maintained', name: 'Maintenance activity (Scorecard)', kind: 'Scorecard check' },
  { key: 's5_committers', name: 'Committers in the last 12 months', kind: 'Repository activity' },
  { key: 's6_open_issues', name: 'Open issues', kind: 'Issue tracker' },
  { key: 's6_closed_issues', name: 'Closed issues', kind: 'Issue tracker' },
  { key: 's7_advisories', name: 'Known vulnerabilities', kind: 'Advisories' },
  { key: 's8_overall', name: 'Scorecard overall', kind: 'Scorecard check' },
  { key: 's9_weekly_downloads', name: 'Weekly downloads', kind: 'Registry statistics' },
];

/**
 * An evidence value as text, or null when there is none ("not recorded"). The value is any JSON; only plain
 * values are shown, never an object, so nothing unexpected is rendered.
 */
export function formatEvidenceValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number')
    return Number.isFinite(value) ? new Intl.NumberFormat('en-GB').format(value) : null;
  if (typeof value === 'string') return value.length > 0 && value.length <= 200 ? value : null;
  if (Array.isArray(value)) return value.length === 0 ? 'none' : `${value.length} listed`;
  return null;
}

const NAME_OF = new Map(SIGNALS.map((s) => [s.key as string, s.name]));
const IDENTIFIER = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;

/**
 * Text from the API as words a reader can use. The API's notes and warnings may name internal identifiers: `as_of` is
 * the date of the evidence (given as `asOf`, already formatted), a signal key such as `s5_committers` is the signal's
 * name, and any other snake_case word has its underscores read as spaces. Nothing else is changed.
 */
export function plainText(text: string, asOf: string | null = null): string {
  return text.replace(IDENTIFIER, (id) => {
    if (id === 'as_of') return asOf && asOf.length > 0 ? asOf : 'the date of this evidence';
    return NAME_OF.get(id)?.toLowerCase() ?? id.replace(/_/g, ' ');
  });
}
