'use client';
import { useRef } from 'react';
import { GraveIcon } from '@/components/art/grave-icon';
import { AppLink } from '@/components/layout/app-link';
import type { ErrorCopy } from '@/lib/api/errors';
import { useFocusHeading } from '@/lib/hooks/use-page';
import { Button, LinkButton } from './button';

/**
 * The themed error of a page (ui-core UI-ERR-3): what happened in a title, one plain sentence, and what to do next.
 * Focus moves to the heading when it appears, so a screen reader announces it. `retryable` decides whether a retry
 * button is offered; the link home is always there.
 */
export function ErrorView({
  copy,
  onRetry,
  backHref,
  backLabel,
  detail,
}: {
  copy: ErrorCopy;
  onRetry?: () => void;
  backHref?: string;
  backLabel?: string;
  /** A line of context, such as the repository that failed. */
  detail?: string;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useFocusHeading(heading, true, copy.title);
  const home = copy.action === 'edit' ? 'Try another repository' : 'Back to the gate';
  return (
    <section
      aria-labelledby="error-title"
      className="container-page flex flex-col items-start gap-5 py-16"
    >
      <GraveIcon type="dead" />
      {detail && <p className="m-0 font-mono text-sm text-bone-quiet">{detail}</p>}
      <h1
        id="error-title"
        ref={heading}
        tabIndex={-1}
        className="m-0 font-display text-[clamp(36px,5vw,60px)] font-semibold leading-[1.05] outline-none"
      >
        {copy.title}
      </h1>
      <p className="m-0 max-w-xl text-lg text-bone-soft">{copy.body}</p>
      <div className="flex flex-wrap gap-3">
        {copy.action === 'retry' && onRetry && <Button onClick={onRetry}>Try again</Button>}
        {backHref && (
          <LinkButton href={backHref} variant="secondary">
            {backLabel ?? 'Go back'}
          </LinkButton>
        )}
        <LinkButton href="/" variant={copy.action === 'retry' && onRetry ? 'secondary' : 'primary'}>
          {home}
        </LinkButton>
      </div>
      <p className="m-0 text-sm text-bone-quiet">
        Not what you expected? <AppLink href="/">Start a new exhumation</AppLink>.
      </p>
    </section>
  );
}
