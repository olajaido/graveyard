import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import {
  hauntedGraves,
  hauntedScan,
  HAUNTED_SCAN_ID,
  lodashCertificate,
} from '@/mocks/fixtures/haunted-house';
import { manyGraves } from '@/mocks/fixtures/builders';
import { server, mockApi } from '@/mocks/node';
import { ApiError, createClient } from './client';

const BASE = 'https://api.test';
const client = (timeoutMs?: number) => createClient({ baseUrl: BASE, timeoutMs });
const failure = async (promise: Promise<unknown>): Promise<ApiError> => {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error('expected the call to fail');
};

describe('the four routes', () => {
  it('creates a scan with the documented body, one header and no credentials', async () => {
    const api = mockApi({ createdScanId: HAUNTED_SCAN_ID });
    const seen: { url: string; init: RequestInit }[] = [];
    const spy = createClient({
      baseUrl: BASE,
      fetch: (url, init) => {
        seen.push({ url: String(url), init: init ?? {} });
        return fetch(url, init);
      },
    });
    const accepted = await spy.createScan('olajaido/haunted-house');
    expect(accepted).toEqual({ scanId: HAUNTED_SCAN_ID, status: 'QUEUED' });
    expect(api.posted).toEqual(['olajaido/haunted-house']);
    expect(seen).toHaveLength(1);
    expect(seen[0]?.url).toBe(`${BASE}/v1/scans`);
    expect(seen[0]?.init.method).toBe('POST');
    expect(seen[0]?.init.credentials).toBe('omit');
    expect(seen[0]?.init.headers).toEqual({ 'content-type': 'application/json' });
    expect(JSON.parse(String(seen[0]?.init.body))).toEqual({
      source: { type: 'github', repo: 'olajaido/haunted-house' },
    });
  });

  it('reads a scan', async () => {
    mockApi();
    expect(await client().getScan(HAUNTED_SCAN_ID)).toEqual(hauntedScan);
  });

  it('reads a certificate by encoded purl', async () => {
    const api = mockApi();
    const cert = await client().getGrave(HAUNTED_SCAN_ID, 'pkg:npm/lodash.template@3.6.2');
    expect(cert).toEqual(lodashCertificate);
    expect(api.calls.at(-1)).toBe(
      `GET /v1/scans/${HAUNTED_SCAN_ID}/graves/pkg%3Anpm%2Flodash.template%403.6.2`,
    );
  });

  it('encodes a scoped npm purl for the path (its own %40 becomes %2540)', async () => {
    const graves = manyGraves(3).map((g, i) =>
      i === 0 ? { ...g, purl: 'pkg:npm/%40babel/core@7.0.0' } : g,
    );
    const api = mockApi({
      scans: { [HAUNTED_SCAN_ID]: hauntedScan },
      graves: { [HAUNTED_SCAN_ID]: graves },
      certificates: {},
    });
    const cert = await client().getGrave(HAUNTED_SCAN_ID, 'pkg:npm/%40babel/core@7.0.0');
    expect(cert.purl).toBe('pkg:npm/%40babel/core@7.0.0');
    expect(api.calls.at(-1)).toContain('/graves/pkg%3Anpm%2F%2540babel%2Fcore%407.0.0');
  });

  it('never puts a slash of the purl in the path unencoded', async () => {
    const api = mockApi();
    await client()
      .getGrave(HAUNTED_SCAN_ID, 'pkg:pypi/pycrypto@2.6.1')
      .catch(() => undefined);
    const call = api.calls.at(-1)!;
    expect(call.split('/graves/')[1]).not.toContain('/');
  });
});

describe('listing graves', () => {
  it('reads all pages with the cursor the API returns, 200 at a time', async () => {
    const graves = manyGraves(450);
    const api = mockApi({
      scans: { [HAUNTED_SCAN_ID]: hauntedScan },
      graves: { [HAUNTED_SCAN_ID]: graves },
    });
    const result = await client().listGraves(HAUNTED_SCAN_ID);
    expect(result.total).toBe(450);
    expect(result.items).toEqual(graves);
    expect(api.calls.filter((c) => c.includes('/graves'))).toEqual([
      `GET /v1/scans/${HAUNTED_SCAN_ID}/graves`,
      `GET /v1/scans/${HAUNTED_SCAN_ID}/graves`,
      `GET /v1/scans/${HAUNTED_SCAN_ID}/graves`,
    ]);
  });

  it('passes the cursor back unchanged and asks for 200', async () => {
    const seen: string[] = [];
    server.use(
      http.get(/\/v1\/scans\/[^/]+\/graves$/, ({ request }) => {
        seen.push(new URL(request.url).search);
        const cursor = new URL(request.url).searchParams.get('cursor');
        return HttpResponse.json({
          scanId: HAUNTED_SCAN_ID,
          total: 2,
          items: [],
          nextCursor: cursor === null ? 'opaque/+=cursor' : null,
        });
      }),
    );
    await client().listGraves(HAUNTED_SCAN_ID);
    expect(seen).toEqual([
      '?limit=200',
      `?limit=200&cursor=${encodeURIComponent('opaque/+=cursor')}`,
    ]);
  });

  it('reads the real capture in one page', async () => {
    mockApi();
    const result = await client().listGraves(HAUNTED_SCAN_ID);
    expect(result).toEqual({ total: 137, items: hauntedGraves.items });
  });

  it('fails instead of truncating when the pages never end', async () => {
    server.use(
      http.get(/\/graves$/, () =>
        HttpResponse.json({ scanId: HAUNTED_SCAN_ID, total: 9, items: [], nextCursor: 'again' }),
      ),
    );
    expect((await failure(client().listGraves(HAUNTED_SCAN_ID))).kind).toBe('parse');
  });
});

describe('failures', () => {
  it('turns a problem body into a problem error with its fixed detail', async () => {
    mockApi();
    const error = await failure(client().getScan('01M84GKAYX7D2JGJ1PYN5JGSS7-0000000000000000'));
    expect(error).toMatchObject({ kind: 'problem', status: 404, detail: 'No such scan.' });
  });

  it('keeps the status of an error that has no problem body', async () => {
    server.use(
      http.get(/\/v1\/scans\/x$/, () => new HttpResponse('Service Unavailable', { status: 503 })),
    );
    expect(await failure(client().getScan('x'))).toMatchObject({
      kind: 'problem',
      status: 503,
      detail: undefined,
    });
  });

  it('reports a failed fetch as network', async () => {
    server.use(http.get(/\/v1\/scans\/x$/, () => HttpResponse.error()));
    expect((await failure(client().getScan('x'))).kind).toBe('network');
  });

  it('times out', async () => {
    mockApi({ delayMs: 400 });
    expect((await failure(client(30).getScan(HAUNTED_SCAN_ID))).kind).toBe('timeout');
  });

  it('reports a body it cannot read as parse', async () => {
    server.use(http.get(/\/v1\/scans\/x$/, () => new HttpResponse('<html>', { status: 200 })));
    expect((await failure(client().getScan('x'))).kind).toBe('parse');
    server.use(http.get(/\/v1\/scans\/y$/, () => HttpResponse.json({ nope: true })));
    expect((await failure(client().getScan('y'))).kind).toBe('parse');
    server.use(http.get(/\/v1\/scans\/z\/graves$/, () => HttpResponse.json({ items: 'no' })));
    expect((await failure(client().listGraves('z'))).kind).toBe('parse');
  });

  it('does not report a call the caller cancelled as a failure of the API', async () => {
    mockApi({ delayMs: 200 });
    const controller = new AbortController();
    const promise = client().getScan(HAUNTED_SCAN_ID, controller.signal);
    controller.abort();
    await expect(promise).rejects.not.toBeInstanceOf(ApiError);
  });

  it('never leaks an exception message', async () => {
    server.use(http.get(/\/v1\/scans\/x$/, () => HttpResponse.error()));
    const error = await failure(client().getScan('x'));
    expect(error.message).toBe('network');
  });
});

describe('the base URL', () => {
  it('may be empty (same origin) and may end with a slash', async () => {
    mockApi();
    expect((await createClient({ baseUrl: `${BASE}/` }).getScan(HAUNTED_SCAN_ID)).scanId).toBe(
      HAUNTED_SCAN_ID,
    );
  });
});
