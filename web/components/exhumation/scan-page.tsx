'use client';
import { useRef } from 'react';
import { ResultsPage } from '@/components/graveyard/results-page';
import { LinkButton } from '@/components/ui/button';
import { CopyLinkButton } from '@/components/ui/copy-link-button';
import { ErrorView } from '@/components/ui/error-view';
import { NotFoundView } from '@/components/ui/not-found-view';
import { PageShell } from '@/components/layout/page-shell';
import { SiteFooter } from '@/components/layout/site-footer';
import { SiteHeader } from '@/components/layout/site-header';
import type { Client } from '@/lib/api/client';
import { getClient } from '@/lib/api/config';
import { copyForCode } from '@/lib/api/errors';
import { useFocusHeading, usePageTitle } from '@/lib/hooks/use-page';
import { useQueryString } from '@/lib/hooks/use-query-state';
import { useScanPoll } from '@/lib/hooks/use-scan-poll';
import { parseScanQuery } from '@/lib/model/route';
import { ExhumationView } from './exhumation-view';

const LOST = {
  title: 'Lost the trail',
  body: 'We could not reach the graveyard to follow this scan. It keeps digging without us. Try again to pick the trail up.',
  action: 'retry',
  retryable: true,
} as const;

function Waiting({ text }: { text: string }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useFocusHeading(heading, true);
  return (
    <div className="container-page py-16" role="status">
      <h1
        ref={heading}
        tabIndex={-1}
        className="m-0 font-display text-4xl font-semibold outline-none"
      >
        {text}
      </h1>
    </div>
  );
}

/**
 * The page `/scan?id=…` (ui-core section 5 and 7): follows the scan while it runs, then shows the results at the same
 * URL. A link it cannot resolve, a scan the API does not know, a failed scan and a lost connection each have their
 * own themed view.
 */
export function ScanPage({ client = getClient() }: { client?: Client }) {
  const [search] = useQueryString();
  const query = search === null ? null : parseScanQuery(search);
  const scanId = query?.ok ? query.scanId : null;
  const poll = useScanPoll(scanId, client);
  const { scan, phase } = poll;

  const repo = scan?.source.repo;
  usePageTitle(
    search === null
      ? null
      : !query?.ok
        ? 'Not found · Graveyard'
        : phase === 'complete'
          ? null // the results page sets its own
          : phase === 'failed'
            ? `Scan failed · ${repo ?? ''} · Graveyard`
            : repo
              ? `Exhuming ${repo} · Graveyard`
              : 'Exhuming… · Graveyard',
  );

  let headerActions: React.ReactNode = <CopyLinkButton label="Copy link to this scan" />;
  let content: React.ReactNode;
  if (search === null) {
    content = <Waiting text="Reading the map…" />;
  } else if (!query?.ok || phase === 'notfound') {
    headerActions = null;
    content = <NotFoundView kind="scan" />;
  } else if (phase === 'loading') {
    content = <Waiting text="Looking for the plot…" />;
  } else if (phase === 'lost') {
    content = <ErrorView copy={LOST} onRetry={poll.retry} />;
  } else if (phase === 'failed' && scan) {
    const copy = copyForCode(scan.error?.code ?? 'INTERNAL', scan.error?.title);
    content = <ErrorView copy={copy} detail={scan.source.repo} />;
  } else if (phase === 'complete' && scan) {
    headerActions = (
      <div className="flex flex-wrap gap-2.5">
        <CopyLinkButton label="Share results" />
        <LinkButton href="/">Exhume another</LinkButton>
      </div>
    );
    content = <ResultsPage scan={scan} client={client} />;
  } else if (scan) {
    content = <ExhumationView scan={scan} />;
  } else {
    content = <Waiting text="Looking for the plot…" />;
  }

  return (
    <>
      <div className="bg-night">
        <SiteHeader>{headerActions}</SiteHeader>
      </div>
      <PageShell>{content}</PageShell>
      <SiteFooter />
    </>
  );
}
