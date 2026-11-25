import type { ApiError } from './client';
import type { ErrorCode } from './types';

export type ErrorAction = 'retry' | 'edit' | 'home' | 'back';

export interface ErrorCopy {
  title: string;
  body: string;
  action: ErrorAction;
  /** A retry can help. */
  retryable: boolean;
}

/**
 * One themed message for every code of the scan error enum (ui-core UI-ERR-1). The type is a `Record` of the enum, so
 * `tsc` fails when the API gains a code without copy. The backend titles for REPO_NOT_FOUND and NO_MANIFESTS mention
 * an SBOM upload, which this UI does not have, so the text here is the UI's own.
 */
export const ERROR_COPY: Record<ErrorCode, ErrorCopy> = {
  INVALID_INPUT: {
    title: 'That is not a grave site',
    body: 'Enter a public GitHub repository as owner/name, for example olajaido/haunted-house.',
    action: 'edit',
    retryable: false,
  },
  REPO_NOT_FOUND: {
    title: 'No such plot',
    body: 'We could not find that repository, or it is not public. Check the spelling. Private repositories are not supported.',
    action: 'edit',
    retryable: false,
  },
  NO_MANIFESTS: {
    title: 'Nothing buried here',
    body: 'No lockfile we can read was found. We read package-lock.json, uv.lock, poetry.lock and requirements*.txt.',
    action: 'edit',
    retryable: false,
  },
  TOO_LARGE: {
    title: 'Too heavy to lift',
    body: "This repository's lockfiles are larger than a scan accepts.",
    action: 'home',
    retryable: false,
  },
  TREE_TRUNCATED: {
    title: 'The cemetery is too big to map',
    body: 'GitHub returned a partial file list for this repository, so we cannot find every lockfile.',
    action: 'home',
    retryable: false,
  },
  TOO_MANY_PACKAGES: {
    title: 'Too many bodies',
    body: 'This repository has more packages than one scan accepts.',
    action: 'home',
    retryable: false,
  },
  GITHUB_RATE_LIMITED: {
    title: 'GitHub asked us to slow down',
    body: 'GitHub is limiting requests right now. Try again in a few minutes.',
    action: 'retry',
    retryable: true,
  },
  GITHUB_AUTH_FAILED: {
    title: 'The gate is locked',
    body: 'Graveyard could not sign in to GitHub. This is on our side. Try again later.',
    action: 'retry',
    retryable: true,
  },
  SBOM_FAILED: {
    title: 'The tags would not read',
    body: 'We could not build a usable package list from the lockfiles.',
    action: 'home',
    retryable: false,
  },
  SBOM_INVALID: {
    title: 'The tags would not read',
    body: 'We could not build a usable package list from the lockfiles.',
    action: 'home',
    retryable: false,
  },
  TIMEOUT: {
    title: 'The dig took too long',
    body: 'The scan ran past its time limit and was stopped. Try again.',
    action: 'retry',
    retryable: true,
  },
  INTERNAL: {
    title: 'Something went wrong underground',
    body: 'The scan failed because of an internal error. Try again.',
    action: 'retry',
    retryable: true,
  },
};

export const OUTCOME_COPY = {
  tooBig: {
    title: 'That request was too big',
    body: 'Send only an owner/name.',
    action: 'edit',
    retryable: false,
  },
  tooMany: {
    title: 'Too many digs at once',
    body: 'Wait a minute, then try again.',
    action: 'retry',
    retryable: true,
  },
  resting: {
    title: 'The crypt is resting',
    body: 'New scans are paused. Scans that already finished stay readable.',
    action: 'home',
    retryable: false,
  },
  notFound: {
    title: 'This plot is not on the map',
    body: 'Scans are kept for 30 days, and the link may be mistyped.',
    action: 'home',
    retryable: false,
  },
  badGrave: {
    title: 'That grave marker is not valid',
    body: 'The package link is not well formed.',
    action: 'back',
    retryable: false,
  },
  unreachable: {
    title: 'The path is out of reach',
    body: 'We could not reach the graveyard. Check your connection and try again.',
    action: 'retry',
    retryable: true,
  },
  unreadable: {
    title: 'Unreadable tags',
    body: 'The graveyard answered with something we could not read.',
    action: 'retry',
    retryable: true,
  },
  generic: {
    title: 'Something went wrong',
    body: 'Please try again.',
    action: 'home',
    retryable: false,
  },
} as const satisfies Record<string, ErrorCopy>;

/** The message for the `error.code` of a failed scan. An unknown code falls back to the server's own title. */
export function copyForCode(code: string, serverTitle?: string): ErrorCopy {
  if (Object.hasOwn(ERROR_COPY, code)) return ERROR_COPY[code as ErrorCode];
  return {
    ...OUTCOME_COPY.generic,
    body: serverTitle && serverTitle.length <= 200 ? serverTitle : OUTCOME_COPY.generic.body,
  };
}

export type CallContext = 'create' | 'scan' | 'grave';

/** The message for a failed call (UI-ERR-2). */
export function copyForApiError(error: ApiError, context: CallContext): ErrorCopy {
  if (error.kind === 'network' || error.kind === 'timeout') return OUTCOME_COPY.unreachable;
  if (error.kind === 'parse') return OUTCOME_COPY.unreadable;
  const status = error.status ?? 0;
  if (context === 'create') {
    if (status === 400) return ERROR_COPY.INVALID_INPUT;
    if (status === 413) return OUTCOME_COPY.tooBig;
    if (status === 429) return OUTCOME_COPY.tooMany;
    if (status === 503) return OUTCOME_COPY.resting;
    return ERROR_COPY.INTERNAL;
  }
  if (status === 404) return OUTCOME_COPY.notFound;
  if (status === 400 && context === 'grave') return OUTCOME_COPY.badGrave;
  if (status === 429) return OUTCOME_COPY.unreachable;
  return ERROR_COPY.INTERNAL;
}
