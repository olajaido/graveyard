import type { Certificate, GravePage, GraveSummary, Problem, Scan, ScanAccepted } from './types';

export type ApiErrorKind = 'problem' | 'network' | 'timeout' | 'parse';

/**
 * Every failure of a call, as one error (ui-core UI-API-3). `problem` is an HTTP error status: `status` is always set
 * and `detail` is the fixed text of an RFC 9457 body when there is one. `network` also covers a CORS or throttle answer
 * the browser hides. The message is never shown to people; the copy comes from `errors.ts`.
 */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly detail?: string;
  constructor(kind: ApiErrorKind, status?: number, detail?: string) {
    super(`${kind}${status ? ` ${status}` : ''}`);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

export interface ClientOptions {
  /** The API origin. An empty string means the same origin as the site. */
  baseUrl: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

export interface Client {
  createScan(repo: string, signal?: AbortSignal): Promise<ScanAccepted>;
  getScan(scanId: string, signal?: AbortSignal): Promise<Scan>;
  listGraves(
    scanId: string,
    signal?: AbortSignal,
  ): Promise<{ total: number; items: GraveSummary[] }>;
  getGrave(scanId: string, purl: string, signal?: AbortSignal): Promise<Certificate>;
}

export const PAGE_LIMIT = 200;
export const MAX_PAGES = 20;
export const TIMEOUT_MS = 15_000;

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

function isProblem(v: unknown): v is Problem {
  return (
    isObject(v) &&
    typeof v.type === 'string' &&
    typeof v.title === 'string' &&
    typeof v.status === 'number' &&
    typeof v.detail === 'string'
  );
}

function isScan(v: unknown): v is Scan {
  return (
    isObject(v) && typeof v.scanId === 'string' && typeof v.status === 'string' && 'stage' in v
  );
}

function isGravePage(v: unknown): v is GravePage {
  return isObject(v) && Array.isArray(v.items) && typeof v.total === 'number' && 'nextCursor' in v;
}

function isCertificate(v: unknown): v is Certificate {
  return isObject(v) && typeof v.purl === 'string' && typeof v.state === 'string';
}

function isAccepted(v: unknown): v is ScanAccepted {
  return isObject(v) && typeof v.scanId === 'string';
}

export function createClient({
  baseUrl,
  fetch: fetchFn,
  timeoutMs = TIMEOUT_MS,
}: ClientOptions): Client {
  const origin = baseUrl.replace(/\/+$/, '');

  async function request(path: string, init: RequestInit, outer?: AbortSignal): Promise<unknown> {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const onAbort = () => controller.abort();
    if (outer?.aborted) controller.abort();
    outer?.addEventListener('abort', onAbort, { once: true });
    let response: Response;
    try {
      // Only the four documented routes, built from the base URL and encoded parts; no credentials (UI-API-2).
      response = await (fetchFn ?? globalThis.fetch)(`${origin}${path}`, {
        ...init,
        credentials: 'omit',
        signal: controller.signal,
      });
    } catch (error) {
      if (outer?.aborted) throw error; // the caller went away: not a failure to report
      throw new ApiError(timedOut ? 'timeout' : 'network');
    } finally {
      clearTimeout(timer);
      outer?.removeEventListener('abort', onAbort);
    }
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      if (response.ok) throw new ApiError('parse');
    }
    if (!response.ok) {
      throw new ApiError('problem', response.status, isProblem(body) ? body.detail : undefined);
    }
    return body;
  }

  const scanPath = (scanId: string) => `/v1/scans/${encodeURIComponent(scanId)}`;

  return {
    async createScan(repo, signal) {
      const body = await request(
        '/v1/scans',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ source: { type: 'github', repo } }),
        },
        signal,
      );
      if (!isAccepted(body)) throw new ApiError('parse');
      return body;
    },
    async getScan(scanId, signal) {
      const body = await request(scanPath(scanId), { method: 'GET' }, signal);
      if (!isScan(body)) throw new ApiError('parse');
      return body;
    },
    async listGraves(scanId, signal) {
      const items: GraveSummary[] = [];
      let total = 0;
      let cursor: string | null = null;
      for (let page = 0; page < MAX_PAGES; page++) {
        const query: string = `?limit=${PAGE_LIMIT}${cursor === null ? '' : `&cursor=${encodeURIComponent(cursor)}`}`;
        const body = await request(`${scanPath(scanId)}/graves${query}`, { method: 'GET' }, signal);
        if (!isGravePage(body)) throw new ApiError('parse');
        items.push(...body.items);
        total = body.total;
        cursor = body.nextCursor;
        if (cursor === null) return { total, items };
      }
      throw new ApiError('parse'); // more pages than a scan can have: never truncate silently
    },
    async getGrave(scanId, purl, signal) {
      const body = await request(
        `${scanPath(scanId)}/graves/${encodeURIComponent(purl)}`,
        { method: 'GET' },
        signal,
      );
      if (!isCertificate(body)) throw new ApiError('parse');
      return body;
    },
  };
}
