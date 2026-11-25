import { delay, http, HttpResponse, type HttpHandler } from 'msw';
import type { Certificate, GraveSummary, Scan } from '@/lib/api/types';
import { SCAN_ID_PATTERN } from '@/lib/model/route';
import {
  hauntedGraves,
  hauntedScan,
  HAUNTED_SCAN_ID,
  lodashCertificate,
} from './fixtures/haunted-house';
import { minimalCertificate } from './fixtures/builders';

/** What a scan answers to successive reads: each read takes the next entry and the last one repeats. */
export type Script = Scan[];

export interface MockOptions {
  /** The answers of `GET /v1/scans/{id}`, per scan. A single scan is a script of one. */
  scans?: Record<string, Script | Scan>;
  /** The graves of each scan, as the API lists them (highest priority first). */
  graves?: Record<string, GraveSummary[]>;
  /** Certificates by scan and purl. A grave without one gets a certificate with every optional field empty. */
  certificates?: Record<string, Record<string, Certificate>>;
  /** The ID that `POST /v1/scans` returns. Default: the haunted-house scan. */
  createdScanId?: string;
  /** Answer `POST /v1/scans` with this error instead of 202. */
  createError?: { status: number; code?: string };
  /** Fail the next call with a network error, for each path that matches. */
  networkError?: (method: string, pathname: string) => boolean;
  /** A pause before every answer, in ms. */
  delayMs?: number;
}

export interface MockApi {
  handlers: HttpHandler[];
  /** Every call, in order: `GET /v1/scans/{id}`. For assertions. */
  calls: string[];
  /** The repos posted. */
  posted: string[];
  /** How many times each scan was read. */
  reads: Record<string, number>;
  reset(): void;
}

const problem = (status: number, detail: string) =>
  HttpResponse.json(
    { type: 'about:blank', title: status === 404 ? 'Not found' : 'Error', status, detail },
    { status, headers: { 'content-type': 'application/problem+json' } },
  );

/** The default world: one finished scan, olajaido/haunted-house, with its real graves and one real certificate. */
export function defaultWorld(): Required<Pick<MockOptions, 'scans' | 'graves' | 'certificates'>> {
  return {
    scans: { [HAUNTED_SCAN_ID]: hauntedScan },
    graves: { [HAUNTED_SCAN_ID]: hauntedGraves.items },
    certificates: { [HAUNTED_SCAN_ID]: { [lodashCertificate.purl]: lodashCertificate } },
  };
}

export function createMockApi(options: MockOptions = {}): MockApi {
  const world = defaultWorld();
  const scans = options.scans ?? world.scans;
  const graves = options.graves ?? world.graves;
  const certificates = options.certificates ?? world.certificates;
  const api: MockApi = {
    handlers: [],
    calls: [],
    posted: [],
    reads: {},
    reset() {
      api.calls.length = 0;
      api.posted.length = 0;
      for (const k of Object.keys(api.reads)) delete api.reads[k];
    },
  };

  api.handlers = [
    http.all(/\/v1\/scans(\/|$)/, async ({ request }) => {
      const url = new URL(request.url);
      const method = request.method;
      const path = url.pathname.slice(url.pathname.indexOf('/v1/scans'));
      api.calls.push(`${method} ${path}`);
      if (options.delayMs) await delay(options.delayMs);
      if (options.networkError?.(method, path)) return HttpResponse.error();

      if (path === '/v1/scans') {
        if (method !== 'POST') return problem(404, 'No such route.');
        const body = (await request.json().catch(() => null)) as {
          source?: { type?: string; repo?: string };
        } | null;
        const repo = body?.source?.repo;
        if (body?.source?.type !== 'github' || typeof repo !== 'string')
          return problem(400, 'The request is not valid.');
        api.posted.push(repo);
        if (options.createError)
          return problem(options.createError.status, 'The scan could not be started.');
        return HttpResponse.json(
          { scanId: options.createdScanId ?? HAUNTED_SCAN_ID, status: 'QUEUED' },
          {
            status: 202,
            headers: { location: `/v1/scans/${options.createdScanId ?? HAUNTED_SCAN_ID}` },
          },
        );
      }

      const match = /^\/v1\/scans\/([^/]+)(?:\/graves(?:\/(.+))?)?$/.exec(path);
      const scanId = match?.[1] ? decodeURIComponent(match[1]) : '';
      if (method !== 'GET' || !match || !SCAN_ID_PATTERN.test(scanId) || !(scanId in scans)) {
        return problem(404, 'No such scan.');
      }

      if (!path.includes('/graves')) {
        const entry = scans[scanId]!;
        const script = Array.isArray(entry) ? entry : [entry];
        const read = api.reads[scanId] ?? 0;
        api.reads[scanId] = read + 1;
        return HttpResponse.json(script[Math.min(read, script.length - 1)]);
      }

      const list = graves[scanId] ?? [];
      if (match[2] === undefined) {
        const limit = Number(url.searchParams.get('limit') ?? 50);
        const offset = Number(url.searchParams.get('cursor') ?? 0);
        if (
          !Number.isInteger(limit) ||
          limit < 1 ||
          limit > 200 ||
          !Number.isInteger(offset) ||
          offset < 0
        ) {
          return problem(400, 'A query parameter is not valid.');
        }
        const page = list.slice(offset, offset + limit);
        const more = offset + limit < list.length;
        return HttpResponse.json({
          scanId,
          total: list.length,
          items: page,
          nextCursor: more ? String(offset + limit) : null,
        });
      }

      const purl = decodeURIComponent(match[2]);
      if (!purl.startsWith('pkg:')) return problem(400, 'The package URL is not valid.');
      const found = certificates[scanId]?.[purl];
      if (found) return HttpResponse.json(found);
      const summary = list.find((g) => g.purl === purl);
      return summary
        ? HttpResponse.json(minimalCertificate(summary))
        : problem(404, 'No such package in this scan.');
    }),
  ];
  return api;
}
