'use client';
import { useState } from 'react';
import { Button } from './button';
import { StatusRegion } from './status-region';

type State = 'idle' | 'copied' | 'manual';

/**
 * Copies the address of the page. The clipboard can be refused (an old browser, a blocked permission); then the link
 * is shown in a field, selected, so it can still be copied by hand. The result is announced in the status region.
 */
export function CopyLinkButton({ label, className }: { label: string; className?: string }) {
  const [state, setState] = useState<State>('idle');
  const [url, setUrl] = useState('');

  async function copy() {
    const href = window.location.href;
    setUrl(href);
    try {
      await navigator.clipboard.writeText(href);
      setState('copied');
    } catch {
      setState('manual');
    }
  }

  const message =
    state === 'copied' ? 'Link copied.' : state === 'manual' ? 'Copy the link from the box.' : '';
  return (
    <span className={`inline-flex flex-wrap items-center gap-2 ${className ?? ''}`}>
      <Button variant="secondary" onClick={copy}>
        {state === 'copied' ? 'Link copied' : label}
      </Button>
      {state === 'manual' && (
        <input
          readOnly
          value={url}
          aria-label="Link to copy"
          autoFocus
          onFocus={(e) => e.currentTarget.select()}
          className="h-11 w-64 max-w-full rounded-md border border-control-line bg-ground px-3 font-mono text-sm text-bone"
        />
      )}
      <StatusRegion message={message} />
    </span>
  );
}
