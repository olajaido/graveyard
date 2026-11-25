'use client';
import { AppLink } from '@/components/layout/app-link';
import { PageShell } from '@/components/layout/page-shell';
import { CopyLinkButton } from '@/components/ui/copy-link-button';
import { ErrorView } from '@/components/ui/error-view';
import { NotFoundView } from '@/components/ui/not-found-view';
import type { Client } from '@/lib/api/client';
import { getClient } from '@/lib/api/config';
import { ApiError } from '@/lib/api/client';
import { copyForApiError } from '@/lib/api/errors';
import type { Scan } from '@/lib/api/types';
import { usePageTitle } from '@/lib/hooks/use-page';
import { useQueryString } from '@/lib/hooks/use-query-state';
import { useResource } from '@/lib/hooks/use-resource';
import { parseGraveQuery, scanHref, SCAN_ID_PATTERN } from '@/lib/model/route';
import { CertificateView } from './certificate-view';

/**
 * The page `/grave?scan=…&purl=…` (ui-core section 9). It loads the certificate, the scan (for the repository name of the
 * back link) and, without waiting for it, the graves list (for the state of the packages on the path). Unknown links and
 * unknown packages show the themed 404 with a way back to the scan.
 */
export function CertificatePage({ client = getClient() }: { client?: Client }) {
  const [search] = useQueryString();
  const query = search === null ? null : parseGraveQuery(search);
  const scanId = query?.ok ? query.scanId : null;
  const purl = query?.ok ? query.purl : null;

  const grave = useResource(
    scanId && purl ? `grave:${scanId}:${purl}` : null,
    (signal) => client.getGrave(scanId!, purl!, signal),
    () => true,
  );
  const scan = useResource<Scan>(
    scanId ? `scan-meta:${scanId}` : null,
    (signal) => client.getScan(scanId!, signal),
    (s) => s.status === 'COMPLETE',
  );
  const graves = useResource(
    scanId ? `graves:${scanId}` : null,
    (signal) => client.listGraves(scanId!, signal),
    () => true,
  );

  const repo = scan.status === 'ready' ? scan.data.source.repo : null;
  const rawScanId = search === null ? null : new URLSearchParams(search).get('scan');
  const backTarget = rawScanId && SCAN_ID_PATTERN.test(rawScanId) ? scanHref(rawScanId) : '/';
  const backLabel = repo
    ? `Back to ${repo}`
    : backTarget === '/'
      ? 'Back to the gate'
      : 'Back to the scan';
  usePageTitle(search === null ? null : query?.ok ? null : 'Not found · Graveyard');

  let content: React.ReactNode;
  if (search === null) {
    content = (
      <div className="container-page py-16" role="status">
        <p className="m-0 text-bone-muted">Reading the map…</p>
      </div>
    );
  } else if (!query?.ok) {
    content = <NotFoundView kind="grave" />;
  } else if (grave.status === 'loading') {
    content = (
      <div className="container-page py-16" role="status">
        <p className="m-0 text-bone-muted">Reading the certificate…</p>
      </div>
    );
  } else if (grave.status === 'error') {
    const error: ApiError = grave.error;
    content =
      error.kind === 'problem' && error.status === 404 ? (
        <NotFoundView kind="grave" />
      ) : (
        <ErrorView copy={copyForApiError(error, 'grave')} onRetry={grave.reload} />
      );
  } else {
    content = (
      <div className="container-page flex items-start pb-24 pt-14">
        <CertificateView
          certificate={grave.data}
          scanId={query.scanId}
          repo={repo}
          graves={graves.status === 'ready' ? graves.data.items : null}
        />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-ground-cert">
      <header className="border-b border-hairline">
        <div className="container-page flex flex-wrap items-center justify-between gap-4 py-5">
          <AppLink
            href={backTarget}
            className="inline-flex items-center gap-2 text-[15px] text-bone-muted no-underline hover:text-bone"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
              focusable="false"
            >
              <path d="M15 18l-6-6 6-6" />
            </svg>
            {backLabel}
          </AppLink>
          <CopyLinkButton label="Copy certificate link" />
        </div>
      </header>
      <PageShell>{content}</PageShell>
    </div>
  );
}
