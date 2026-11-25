'use client';
import { domAnimation, LazyMotion, MotionConfig } from 'framer-motion';
import type { ReactNode } from 'react';

/**
 * Framer Motion for the pages of a scan and of a grave only: the landing page has none, to keep it light (ui-core
 * UI-Q-6). `reducedMotion="user"` follows the browser setting; entrances also check it themselves (see `Plot`).
 */
export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user">
      <LazyMotion features={domAnimation}>{children}</LazyMotion>
    </MotionConfig>
  );
}
