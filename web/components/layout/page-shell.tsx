import type { ReactNode } from 'react';

/** The `<main>` that the skip link targets. Focusable by script only (focus moves to the h1 after navigation). */
export function PageShell({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <main id="main" tabIndex={-1} className={`outline-none ${className ?? ''}`}>
      {children}
    </main>
  );
}
