import { PageShell } from '@/components/layout/page-shell';
import { SiteHeader } from '@/components/layout/site-header';
import { NotFoundView } from '@/components/ui/not-found-view';

export default function NotFound() {
  return (
    <>
      <SiteHeader />
      <PageShell>
        <NotFoundView kind="path" />
      </PageShell>
    </>
  );
}
