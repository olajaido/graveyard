import { OUTCOME_COPY, type ErrorCopy } from '@/lib/api/errors';
import { ErrorView } from './error-view';

const PATH: ErrorCopy = {
  title: 'This page is not on the map',
  body: 'Check the address, or start again from the gate. Scans are kept for 30 days.',
  action: 'home',
  retryable: false,
};

/**
 * The themed 404 (ui-core UI-RT-3): an unknown path, an unresolvable link, an unknown scan or an unknown grave. It
 * always links home and, when it has one, back to the scan.
 */
export function NotFoundView({
  kind = 'scan',
  backHref,
  backLabel,
  detail,
}: {
  kind?: 'scan' | 'grave' | 'path';
  backHref?: string;
  backLabel?: string;
  detail?: string;
}) {
  const copy: ErrorCopy =
    kind === 'path'
      ? PATH
      : kind === 'grave'
        ? {
            ...OUTCOME_COPY.notFound,
            title: 'No such grave in this plot',
            body: 'This package is not part of the scan, or the link is mistyped. Scans are kept for 30 days.',
          }
        : OUTCOME_COPY.notFound;
  return <ErrorView copy={copy} backHref={backHref} backLabel={backLabel} detail={detail} />;
}
