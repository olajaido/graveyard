import { describe, expect, it } from 'vitest';
import { linkLabel, LINK_HOSTS, safeLink } from './links';
import { formatEvidenceValue, SIGNALS } from './signals';

describe('safeLink', () => {
  it.each([
    'https://www.npmjs.com/package/lodash.template/v/3.6.2',
    'https://pypi.org/project/pycrypto/2.6.1/',
    'https://github.com/lodash/lodash',
    'https://osv.dev/vulnerability/GHSA-35jh-r3h4-6jhm',
    'https://deps.dev/npm/lodash.template/3.6.2',
  ])('renders %s', (url) => expect(safeLink(url)).toBe(url));

  it.each([
    'http://github.com/a/b',
    'javascript:alert(1)',
    'data:text/html,<script>1</script>',
    'https://evil.example/a',
    'https://github.com.evil.example/a',
    'https://evil.example@github.com/a',
    'https://user:pw@github.com/a',
    'https://api.github.com/graphql',
    'https://registry.npmjs.org/x',
    'https://npmjs.com/package/x',
    '//github.com/a',
    'github.com/a',
    '',
    'not a url',
  ])('refuses %j', (url) => expect(safeLink(url)).toBeNull());

  it('allows the five hosts', () => {
    expect(LINK_HOSTS).toEqual(['www.npmjs.com', 'pypi.org', 'github.com', 'osv.dev', 'deps.dev']);
  });
});

describe('linkLabel', () => {
  it('reads the notice when the signal says the package is flagged', () => {
    expect(linkLabel({ kind: 'registry', url: 'https://www.npmjs.com/package/x' }, true)).toBe(
      'Read the notice on npmjs.com',
    );
    expect(linkLabel({ kind: 'registry', url: 'https://pypi.org/project/x/' }, true)).toBe(
      'Read the notice on pypi.org',
    );
    expect(linkLabel({ kind: 'registry', url: 'https://www.npmjs.com/package/x' }, false)).toBe(
      'View on npmjs.com',
    );
  });
  it('names the other kinds by what they open', () => {
    expect(linkLabel({ kind: 'repository', url: 'https://github.com/a/b' }, false)).toBe(
      'See the repository on github.com',
    );
    expect(linkLabel({ kind: 'advisory', url: 'https://osv.dev/vulnerability/X' }, false)).toBe(
      'Read the advisory on osv.dev',
    );
    expect(linkLabel({ kind: 'deps_dev', url: 'https://deps.dev/npm/x/1' }, false)).toBe(
      'See the scores on deps.dev',
    );
  });
});

describe('formatEvidenceValue', () => {
  it.each([
    [true, 'yes'],
    [false, 'no'],
    [9, '9'],
    [3987430, '3,987,430'],
    [7.5, '7.5'],
    ['2026-04-01', '2026-04-01'],
    [[], 'none'],
    [[{ id: 'x' }], '1 listed'],
    [null, null],
    [undefined, null],
    [{ a: 1 }, null],
    [Number.NaN, null],
    ['', null],
    ['x'.repeat(201), null],
  ])('%j', (value, text) => expect(formatEvidenceValue(value)).toBe(text));
});

describe('SIGNALS', () => {
  it('lists the eleven evidence keys once, in the order of the certificate', () => {
    expect(SIGNALS.map((s) => s.key)).toEqual([
      's1_declared_death',
      's1b_version_deprecated',
      's2_latest_release_at',
      's3_last_push_at',
      's4_maintained',
      's5_committers',
      's6_open_issues',
      's6_closed_issues',
      's7_advisories',
      's8_overall',
      's9_weekly_downloads',
    ]);
  });
});
