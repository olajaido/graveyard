import { describe, expect, it } from 'vitest';
import {
  graveHref,
  parseGraveQuery,
  parseScanQuery,
  parseViewState,
  scanHref,
  viewStateSearch,
} from './route';

const ID = '01M84GKAYX7D2JGJ1PYN5JGSS7-e066cd4c1ba726a8';

describe('scan query', () => {
  it('reads a valid id', () => {
    expect(parseScanQuery(`?id=${ID}`)).toEqual({ ok: true, scanId: ID });
    expect(parseScanQuery(`id=${ID}&view=table`)).toEqual({ ok: true, scanId: ID });
  });
  it.each([
    '',
    '?',
    '?id=',
    '?id=abc',
    `?id=${ID}x`,
    `?id=${ID.toLowerCase()}`,
    `?scan=${ID}`,
    '?id=../../etc/passwd',
    `?id=${encodeURIComponent(`${ID}/graves`)}`,
  ])('refuses %j without any request', (search) => {
    expect(parseScanQuery(search)).toEqual({ ok: false });
  });
});

describe('grave query', () => {
  it('round-trips a plain purl', () => {
    const href = graveHref(ID, 'pkg:npm/lodash.template@3.6.2');
    expect(href).toBe(`/grave?scan=${ID}&purl=pkg%3Anpm%2Flodash.template%403.6.2`);
    expect(parseGraveQuery(href.split('?')[1]!)).toEqual({
      ok: true,
      scanId: ID,
      purl: 'pkg:npm/lodash.template@3.6.2',
    });
  });
  it('round-trips a scoped npm purl, whose own % is encoded again', () => {
    const purl = 'pkg:npm/%40babel/core@7.0.0';
    const href = graveHref(ID, purl);
    expect(href).toContain('purl=pkg%3Anpm%2F%2540babel%2Fcore%407.0.0');
    expect(parseGraveQuery(href.split('?')[1]!)).toEqual({ ok: true, scanId: ID, purl });
  });
  it('decodes exactly once', () => {
    const q = `scan=${ID}&purl=${encodeURIComponent('pkg:npm/a%2Fb@1')}`;
    expect(parseGraveQuery(q)).toMatchObject({ purl: 'pkg:npm/a%2Fb@1' });
  });
  it.each([
    '',
    `?scan=${ID}`,
    `?purl=pkg%3Anpm%2Fa%401`,
    `?scan=bad&purl=pkg%3Anpm%2Fa%401`,
    `?scan=${ID}&purl=npm%2Fa%401`,
    `?scan=${ID}&purl=${'pkg:npm/' + 'a'.repeat(500)}`,
    `?scan=${ID}&purl=`,
  ])('refuses %j', (search) => {
    expect(parseGraveQuery(search)).toEqual({ ok: false });
  });
});

describe('view state', () => {
  it('defaults', () => {
    expect(parseViewState(new URLSearchParams(''))).toEqual({
      view: undefined,
      state: undefined,
      service: undefined,
      sort: 'priority',
      dir: 'desc',
    });
  });
  it('reads valid values and ignores unknown ones', () => {
    const state = parseViewState(
      new URLSearchParams('view=table&state=dead&service=services%2Fworker&sort=package'),
    );
    expect(state).toEqual({
      view: 'table',
      state: 'dead',
      service: 'services/worker',
      sort: 'package',
      dir: 'asc',
    });
    expect(parseViewState(new URLSearchParams('view=x&state=alive&sort=y&dir=up'))).toMatchObject({
      view: undefined,
      state: undefined,
      sort: 'priority',
      dir: 'desc',
    });
  });
  it('writes only what differs from the defaults', () => {
    expect(scanHref(ID)).toBe(`/scan?id=${ID}`);
    expect(scanHref(ID, { view: 'table', state: 'cursed' })).toBe(
      `/scan?id=${ID}&view=table&state=cursed`,
    );
    expect(viewStateSearch({ sort: 'package', dir: 'asc' }).toString()).toBe('sort=package');
    expect(viewStateSearch({ sort: 'package', dir: 'desc' }).toString()).toBe(
      'sort=package&dir=desc',
    );
    expect(viewStateSearch({ sort: 'priority', dir: 'asc' }).toString()).toBe('dir=asc');
  });
  it('keeps unrelated parameters such as id', () => {
    const base = new URLSearchParams(`id=${ID}&view=scene&state=dead`);
    expect(viewStateSearch({ view: 'table' }, base).toString()).toBe(`id=${ID}&view=table`);
  });
});
