import { describe, expect, it } from 'vitest';
import { parseDisplayPurl, parsePackageKey } from './purl';

describe('parseDisplayPurl', () => {
  it('splits a plain npm purl', () => {
    expect(parseDisplayPurl('pkg:npm/lodash.template@3.6.2')).toEqual({
      type: 'npm',
      ecosystemLabel: 'npm',
      namespace: undefined,
      name: 'lodash.template',
      fullName: 'lodash.template',
      version: '3.6.2',
    });
  });
  it('decodes a scoped npm purl', () => {
    expect(parseDisplayPurl('pkg:npm/%40babel/core@7.0.0')).toMatchObject({
      namespace: '@babel',
      name: 'core',
      fullName: '@babel/core',
      version: '7.0.0',
    });
  });
  it('labels PyPI and drops qualifiers and subpath', () => {
    expect(parseDisplayPurl('pkg:pypi/pycrypto@2.6.1?arch=x86#sub/path')).toMatchObject({
      ecosystemLabel: 'PyPI',
      fullName: 'pycrypto',
      version: '2.6.1',
    });
  });
  it('has no version when there is none', () => {
    expect(parseDisplayPurl('pkg:npm/left-pad').version).toBeUndefined();
  });
  it.each(['', 'nonsense', 'pkg:', 'pkg:npm', 'pkg:/x', 'pkg:npm/'])(
    'never throws on %j',
    (text) => {
      const p = parseDisplayPurl(text);
      expect(p.fullName).toBe(text);
      expect(p.type).toBe('unknown');
    },
  );
  it('survives a broken escape', () => {
    expect(parseDisplayPurl('pkg:npm/%E0%A4%A@1').name).toBe('%E0%A4%A');
  });
  it('reads a package key of an example path', () => {
    expect(parsePackageKey('npm/gulp-util@3.0.8')).toMatchObject({
      fullName: 'gulp-util',
      version: '3.0.8',
    });
    expect(parsePackageKey('npm/%40babel/core@7.0.0').fullName).toBe('@babel/core');
  });
});
