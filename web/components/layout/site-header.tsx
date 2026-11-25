import type { ReactNode } from 'react';
import { BrandMark } from '@/components/art/brand-mark';
import { AppLink } from './app-link';

/** The brand and, on the right, the page's nav or actions. `large` is the landing size. */
export function SiteHeader({
  children,
  large = false,
  className = 'relative',
}: {
  children?: ReactNode;
  large?: boolean;
  className?: string;
}) {
  return (
    <header className={className}>
      <div
        className={`container-page flex flex-wrap items-center justify-between gap-4 ${large ? 'py-6' : 'py-5'}`}
      >
        <AppLink href="/" className="flex items-center gap-3 text-bone no-underline">
          {large ? <BrandMark /> : <BrandMark width={22} height={26} strokeWidth={1.8} />}
          <span
            className={`font-display font-bold ${large ? 'text-[28px] tracking-[0.02em]' : 'text-2xl'}`}
          >
            Graveyard
          </span>
        </AppLink>
        {children}
      </div>
    </header>
  );
}
