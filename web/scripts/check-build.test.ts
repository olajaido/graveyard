import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { check, cspProblems } from './check-build.mjs';

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
describe('the CSP drift check (infra-edge EDGE-HDR-2)', () => {
  const page = (body: string, scripts = '') =>
    `<html><head><script src="/_next/static/a.js" async=""></script>${scripts}</head><body>${body}</body></html>`;
  const known =
    '<script id="_R_">(globalThis["TURBOPACK"] || (globalThis["TURBOPACK"] = [])).push({})</script>' +
    '<script>(self.__next_f=self.__next_f||[]).push([0])</script>' +
    '<script>self.__next_f.push([1,"<style> and style=\"x\" inside flight data are text"])</script>';
  it('accepts the three inline scripts of the Next.js export and markup without inline style', () => {
    expect(cspProblems(page('<main class="a"><a href="/scan">x</a></main>', known))).toEqual([]);
  });
  it.each([
    ['another inline script', page('', '<script>alert(1)</script>')],
    ['a style tag', page('<style>a{color:red}</style>', known)],
    ['a style attribute', page('<div style="clip-path:polygon(0 0)">x</div>', known)],
    ['an event handler attribute', page('<img src="/a.png" onerror="x()">', known)],
    ['a javascript: URL', page('<a href="javascript:x()">x</a>', known)],
  ])('flags %s', (_name, html) => {
    expect(cspProblems(html).length).toBeGreaterThan(0);
  });
  it('makes check() fail on a page with a stray inline script', () => {
    const dir = site({ 'index.html': page('', '<script>alert(1)</script>') });
    expect(check(dir).some((p) => p.includes('inline script'))).toBe(true);
  });
});
