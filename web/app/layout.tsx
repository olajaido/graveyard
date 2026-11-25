import type { Metadata, Viewport } from 'next';
import { MockBoot } from '@/components/layout/mock-boot';
import { SkipLink } from '@/components/layout/skip-link';
import { body, display, mono } from './fonts';
import './globals.css';

export const metadata: Metadata = {
  title: 'Graveyard: find the dead dependencies in your project',
  description:
    'Graveyard reads your lockfiles, digs through every transitive dependency, and names the dead, the dying and the cursed, with the evidence to prove it.',
};

export const viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: '#0d0f13' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className="font-sans">
        <MockBoot>
          <SkipLink />
          {children}
        </MockBoot>
      </body>
    </html>
  );
}
