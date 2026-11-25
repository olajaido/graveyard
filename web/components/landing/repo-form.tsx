'use client';
import { useRef, useState } from 'react';
import { useAppRouter } from '@/components/layout/use-app-router';
import { getClient } from '@/lib/api/config';
import { ApiError } from '@/lib/api/client';
import { copyForApiError, ERROR_COPY } from '@/lib/api/errors';
import type { ScanAccepted } from '@/lib/api/types';
import { normaliseRepo } from '@/lib/model/repo-input';
import { scanHref } from '@/lib/model/route';

/** The default repository of the form, as in the mockup. */
export const DEFAULT_REPO = 'olajaido/haunted-house';

type Create = (repo: string) => Promise<ScanAccepted>;

/**
 * The repo form (ui-core UI-LAND-2, UI-LAND-3). It accepts `owner/name` and the GitHub address forms, refuses the rest
 * before any request, posts the scan and moves to its page. An error stays on the page, is tied to the input and takes
 * focus there.
 */
export function RepoForm({ create = (repo) => getClient().createScan(repo) }: { create?: Create }) {
  const router = useAppRouter();
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(DEFAULT_REPO);
  const [error, setError] = useState<{ title: string; body: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function fail(title: string, body: string) {
    setError({ title, body });
    setSubmitting(false);
    // The message is rendered by the time the focus moves.
    queueMicrotask(() => input.current?.focus());
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const parsed = normaliseRepo(value);
    if (!parsed.ok) {
      fail(ERROR_COPY.INVALID_INPUT.title, ERROR_COPY.INVALID_INPUT.body);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const accepted = await create(parsed.repo);
      router.push(scanHref(accepted.scanId));
    } catch (caught) {
      const copy = copyForApiError(
        caught instanceof ApiError ? caught : new ApiError('network'),
        'create',
      );
      fail(copy.title, copy.body);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="flex max-w-[560px] flex-col gap-2.5">
      <label htmlFor="repo" className="text-sm font-medium">
        Public GitHub repository
      </label>
      <div className="flex flex-wrap gap-2.5">
        <div className="flex min-w-0 flex-[1_1_280px] items-center gap-2 rounded-md border border-control-line bg-ground px-3.5">
          <span aria-hidden="true" className="font-mono text-[15px] text-bone-dim">
            github.com/
          </span>
          <input
            id="repo"
            ref={input}
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="owner/repo"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? 'repo-error repo-hint' : 'repo-hint'}
            className="h-[52px] min-w-0 flex-1 border-0 bg-transparent font-mono text-[15px] text-bone"
          />
        </div>
        <button
          type="submit"
          disabled={submitting}
          aria-busy={submitting}
          className="inline-flex h-[54px] cursor-pointer items-center gap-2.5 rounded-md bg-bone px-[26px] text-base font-semibold text-on-bone hover:bg-white disabled:cursor-wait disabled:opacity-80"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#121314"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M14 3l7 7" />
            <path d="M17.5 6.5L8 16" />
            <path d="M8 16l-3 1 -2 4 4-2 1-3" />
          </svg>
          {submitting ? 'Digging…' : 'Exhume'}
        </button>
      </div>
      {error && (
        <p
          id="repo-error"
          className="m-0 rounded-md border border-dead/60 bg-ground px-3 py-2 text-sm text-bone"
        >
          <strong className="font-semibold text-dead">{error.title}.</strong> {error.body}
        </p>
      )}
      <p id="repo-hint" className="m-0 text-[13px] text-bone-quiet">
        Reads <code className="font-mono">package-lock.json</code>,{' '}
        <code className="font-mono">uv.lock</code>, <code className="font-mono">poetry.lock</code>,{' '}
        <code className="font-mono">requirements*.txt</code>. Nothing is installed or run.
      </p>
    </form>
  );
}
