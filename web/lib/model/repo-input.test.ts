import { describe, expect, it } from 'vitest';
import { normaliseRepo } from './repo-input';

describe('normaliseRepo', () => {
  it.each([
    ['olajaido/haunted-house', 'olajaido/haunted-house'],
    ['  olajaido/haunted-house  ', 'olajaido/haunted-house'],
    ['github.com/olajaido/haunted-house', 'olajaido/haunted-house'],
    ['GitHub.com/olajaido/haunted-house', 'olajaido/haunted-house'],
    ['https://github.com/olajaido/haunted-house', 'olajaido/haunted-house'],
    ['http://www.github.com/olajaido/haunted-house/', 'olajaido/haunted-house'],
    ['https://github.com/olajaido/haunted-house.git', 'olajaido/haunted-house'],
    ['https://github.com/olajaido/haunted-house.git/', 'olajaido/haunted-house'],
    ['a/b', 'a/b'],
    ['a-b/c.d_e', 'a-b/c.d_e'],
  ])('accepts %j', (input, repo) => {
    expect(normaliseRepo(input)).toEqual({ ok: true, repo });
  });

  it.each([
    '',
    ' ',
    'olajaido',
    'olajaido/',
    '/haunted-house',
    'a/b/c',
    'https://github.com/a/b/tree/main',
    'https://gitlab.com/a/b',
    'evil.example/a/b',
    'https://evil.example/github.com/a/b',
    'a/b?x=1',
    'a/b#frag',
    'a/b c',
    '-a/b',
    `${'a'.repeat(40)}/b`,
    `a/${'b'.repeat(101)}`,
    'a/..',
    'a/.',
    'a/b\nc',
    '<script>alert(1)</script>/x',
    'a:b/c',
    'a/b@evil.example',
    '../a',
    'git@github.com:a/b.git',
  ])('refuses %j', (input) => {
    expect(normaliseRepo(input)).toEqual({ ok: false });
  });

  it('keeps a name that ends in .git only when nothing is left otherwise', () => {
    expect(normaliseRepo('a/.git')).toEqual({ ok: true, repo: 'a/.git' });
    expect(normaliseRepo('a/x.git')).toEqual({ ok: true, repo: 'a/x' });
  });
});
