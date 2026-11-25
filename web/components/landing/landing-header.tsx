import { SiteHeader } from '@/components/layout/site-header';
import { NAV } from './hero';

/** The banner of the landing page: the brand and the nav, laid over the night scene. */
export function LandingHeader() {
  return (
    <SiteHeader large className="absolute inset-x-0 top-0 z-10">
      <nav aria-label="Main" className="flex flex-wrap items-center gap-x-7 gap-y-2 text-[15px]">
        {NAV.map((item) => (
          <a
            key={item.href}
            href={item.href}
            className="text-bone-muted no-underline hover:text-white"
          >
            {item.label}
          </a>
        ))}
      </nav>
    </SiteHeader>
  );
}
