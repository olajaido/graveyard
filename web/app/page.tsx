import { EvidenceStone } from '@/components/landing/evidence-stone';
import { ExampleStrip } from '@/components/landing/example-strip';
import { Hero } from '@/components/landing/hero';
import { LandingHeader } from '@/components/landing/landing-header';
import { HowItWorks } from '@/components/landing/how-it-works';
import { SixStates } from '@/components/landing/six-states';
import { PageShell } from '@/components/layout/page-shell';
import { SiteFooter } from '@/components/layout/site-footer';

export default function Home() {
  return (
    <>
      <div className="relative">
        <LandingHeader />
        <PageShell>
          <Hero />
          <ExampleStrip />
          <HowItWorks />
          <SixStates />
          <EvidenceStone />
        </PageShell>
      </div>
      <SiteFooter />
    </>
  );
}
