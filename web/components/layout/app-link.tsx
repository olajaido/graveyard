import Link from 'next/link';
import type { ComponentProps } from 'react';

/** The one place components touch `next/link`, so a framework change stays a one-file edit. */
export function AppLink(props: ComponentProps<typeof Link>) {
  return <Link {...props} />;
}
