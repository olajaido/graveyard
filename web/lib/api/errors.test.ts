import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ApiError } from './client';
import { copyForApiError, copyForCode, ERROR_COPY, OUTCOME_COPY } from './errors';

/** The `ErrorCode` enum of backend/api/openapi.yaml, read as text (no YAML parser is needed). */
function enumFromOpenApi(): string[] {
  const text = readFileSync(resolve(process.cwd(), '../backend/api/openapi.yaml'), 'utf8');
  const block =
    /\n {4}ErrorCode:\n[\s\S]*?\n {6}enum:\n((?: {8}- [A-Z_]+\n)+)/.exec(text)?.[1] ?? '';
  return [...block.matchAll(/- ([A-Z_]+)/g)].map((m) => m[1]!);
}

describe('error copy', () => {
  it('has a message for every code of the API enum, and no other', () => {
    const codes = enumFromOpenApi();
    expect(codes).toHaveLength(12);
    expect(Object.keys(ERROR_COPY).sort()).toEqual([...codes].sort());
  });

  it('is typed so a new code without copy fails the type check', () => {
    // The Record<ErrorCode, ErrorCopy> type is the check; this line only proves a lookup is total.
    for (const copy of Object.values(ERROR_COPY)) {
      expect(copy.title.length).toBeGreaterThan(0);
      expect(copy.body.length).toBeGreaterThan(0);
    }
  });

  it('never suggests an SBOM upload or a feature the UI does not have', () => {
    const all = [...Object.values(ERROR_COPY), ...Object.values(OUTCOME_COPY)];
    for (const copy of all) expect(`${copy.title} ${copy.body}`).not.toMatch(/sbom|upload|demo/i);
  });

  it('says what to do and whether a retry helps', () => {
    expect(ERROR_COPY.GITHUB_RATE_LIMITED).toMatchObject({ action: 'retry', retryable: true });
    expect(ERROR_COPY.REPO_NOT_FOUND).toMatchObject({ action: 'edit', retryable: false });
    expect(ERROR_COPY.NO_MANIFESTS.body).toContain('package-lock.json');
  });

  it('falls back to the server title for a code it does not know', () => {
    const copy = copyForCode('FUTURE_CODE', 'The scan hit a new problem.');
    expect(copy.title).toBe('Something went wrong');
    expect(copy.body).toBe('The scan hit a new problem.');
    expect(copyForCode('FUTURE_CODE').body).toBe('Please try again.');
    expect(copyForCode('toString').title).toBe('Something went wrong');
    expect(copyForCode('INTERNAL')).toBe(ERROR_COPY.INTERNAL);
  });
});

describe('copyForApiError', () => {
  const problem = (status: number) => new ApiError('problem', status);
  it.each([
    [400, 'That is not a grave site'],
    [413, 'That request was too big'],
    [429, 'Too many digs at once'],
    [503, 'The crypt is resting'],
    [500, 'Something went wrong underground'],
    [502, 'Something went wrong underground'],
  ])('POST %i', (status, title) => {
    expect(copyForApiError(problem(status), 'create').title).toBe(title);
  });
  it.each([
    [404, 'scan', 'This plot is not on the map'],
    [404, 'grave', 'This plot is not on the map'],
    [400, 'grave', 'That grave marker is not valid'],
    [429, 'scan', 'The path is out of reach'],
    [500, 'scan', 'Something went wrong underground'],
    [503, 'grave', 'Something went wrong underground'],
  ] as const)('GET %i (%s)', (status, context, title) => {
    expect(copyForApiError(problem(status), context).title).toBe(title);
  });
  it('covers network, timeout and parse failures', () => {
    expect(copyForApiError(new ApiError('network'), 'create').title).toBe(
      'The path is out of reach',
    );
    expect(copyForApiError(new ApiError('timeout'), 'scan').retryable).toBe(true);
    expect(copyForApiError(new ApiError('parse'), 'grave').title).toBe('Unreadable tags');
  });
});
