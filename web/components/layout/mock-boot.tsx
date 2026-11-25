'use client';
import { useEffect, useState, type ReactNode } from 'react';

/**
 * Starts the MSW service worker before the app renders, in the test build only (`npm run build:e2e`). In the production
 * build `MOCKING` is the constant `false`, so the import below is dead code and neither `msw` nor the mock handlers are
 * in the output; `scripts/check-build.mjs` fails the build if they ever are (ui-core UI-STK-8).
 */
export function MockBoot({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(process.env.NEXT_PUBLIC_API_MOCKING !== 'enabled');
  useEffect(() => {
    // The condition is inlined by the build: in the production build it is `false` and the import is removed.
    if (process.env.NEXT_PUBLIC_API_MOCKING === 'enabled') {
      void import('@/mocks/browser').then((m) => m.startMockWorker()).then(() => setReady(true));
    }
  }, []);
  return ready ? <>{children}</> : null;
}
