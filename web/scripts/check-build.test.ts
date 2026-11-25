import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { check } from './check-build.mjs';

function site(files: Record<string, string>): string {
  const dir = mkdtempSync(join(tmpdir(), 'gy-build-'));
  for (const [name, text] of Object.entries(files)) {
    mkdirSync(join(dir, name, '..'), { recursive: true });
    writeFileSync(join(dir, name), text);
  }
  return dir;
}

describe('check-build', () => {
  it('passes a clean site', () => {
    expect(
      check(
        site({
          'index.html': '<h1>ok</h1>',
          '_next/static/a.css': '@font-face{src:url(/_next/static/media/a.woff2)}',
        }),
      ),
    ).toEqual([]);
  });

  it.each([
    [
      'a Google Fonts stylesheet',
      { 'index.html': '<link href="https://fonts.googleapis.com/css2?family=Inter">' },
    ],
    [
      'the Google Fonts host in css',
      { 'a.css': '@import url(https://fonts.gstatic.com/s/inter.woff2)' },
    ],
    ['the service worker file', { 'mockServiceWorker.js': '// worker' }],
    ['msw in a bundle', { '_next/static/chunk.js': 'import("msw/browser")' }],
    ['the mock API in a bundle', { '_next/static/chunk.js': 'function createMockApi(){}' }],
    ['the MSW worker setup in a bundle', { '_next/static/chunk.js': 'setupWorker(a)' }],
  ])('fails %s', (_name, files) => {
    expect(check(site(files)).length).toBeGreaterThan(0);
  });

  it('exits 1 on a bad folder and 0 on a good one', () => {
    const bad = site({ 'index.html': 'https://fonts.googleapis.com/x' });
    expect(() =>
      execFileSync('node', ['scripts/check-build.mjs', bad], { stdio: 'pipe' }),
    ).toThrow();
    const good = site({ 'index.html': 'fine' });
    expect(execFileSync('node', ['scripts/check-build.mjs', good]).toString()).toContain(
      'no mock code',
    );
  });
});
