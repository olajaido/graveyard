import { describe, expect, it } from 'vitest';
import { plainText, SIGNALS } from './signals';

describe('plainText', () => {
  it('writes as_of as the date of the evidence', () => {
    expect(plainText('distinct commit authors in the 12 months to as_of', '22 Nov 2026')).toBe(
      'distinct commit authors in the 12 months to 22 Nov 2026',
    );
  });
  it('has words for as_of when the date is not known', () => {
    expect(plainText('in the 12 months to as_of')).toBe(
      'in the 12 months to the date of this evidence',
    );
    expect(plainText('in the 12 months to as_of', '')).toBe(
      'in the 12 months to the date of this evidence',
    );
  });
  it.each(SIGNALS)('writes the key $key as the name of the signal', ({ key, name }) => {
    expect(plainText(`affects ${key}`)).toBe(`affects ${name.toLowerCase()}`);
  });
  it('reads any other snake_case word as words', () => {
    expect(plainText('see latest_release_at and no_fix_known.')).toBe(
      'see latest release at and no fix known.',
    );
  });
  it('leaves text with no identifier as it is', () => {
    const text = 'npm: latest version deprecated OR repo archived; PyPI: repo archived only';
    expect(plainText(text, '1 Jan 2026')).toBe(text);
    expect(plainText('GHSA-35jh-r3h4-6jhm at deps.dev/v3')).toBe(
      'GHSA-35jh-r3h4-6jhm at deps.dev/v3',
    );
  });
});
