import { describe, expect, it } from 'vitest';
import { causeOf, causeOfDeath, largestContribution } from './cause';
import { makeGrave } from './test-data';

describe('causeOf (table)', () => {
  it.each([
    [{ state: 'dead', deadReason: 'declared' }, 'Declared dead by its source'],
    [{ state: 'dead', deadReason: 'score' }, 'High abandonment score'],
    [
      { state: 'dead', deadReason: 'declared', cursed: true },
      'Declared dead by its source; Known vulnerability, no fix available',
    ],
    [{ state: 'ailing' }, 'Signs of neglect'],
    [{ state: 'resting' }, 'Finished and stable'],
    [{ state: 'alive', wounded: true }, 'Upgrade advised'],
    [{ state: 'alive', cursed: true, wounded: true }, 'Known vulnerability, no fix available'],
    [{ state: 'alive' }, ''],
    [{ state: 'unknown' }, ''],
  ] as const)('%j', (over, text) => {
    expect(causeOf(makeGrave({ ...over }))).toBe(text);
  });
});

describe('largestContribution', () => {
  it('picks the largest non-null value and names it', () => {
    expect(largestContribution({ r2: 10, r3: null, r4: 36.4, r8: 11.4 })).toEqual({
      id: 'r4',
      name: 'maintenance activity',
      value: 36.4,
    });
  });
  it('is null when there is nothing above zero', () => {
    expect(largestContribution({ r2: 0, r3: null })).toBeNull();
    expect(largestContribution({})).toBeNull();
    expect(largestContribution(null)).toBeNull();
  });
  it('breaks a tie with the first id and keeps an unknown id as its name', () => {
    expect(largestContribution({ r8: 5, r2: 5 })?.id).toBe('r2');
    expect(largestContribution({ r9: 5 })?.name).toBe('r9');
  });
});

describe('causeOfDeath', () => {
  const base = {
    state: 'dead',
    deadReason: 'declared',
    cursed: false,
    wounded: false,
    contributions: { r2: 0, r8: 2.5 },
  } as const;
  it('is a fixed template over the payload', () => {
    expect(causeOfDeath(base)).toBe(
      'Declared dead: its source reports it as deprecated, archived or retired. Largest contribution to its score: Scorecard overall.',
    );
  });
  it('adds the overlay sentences', () => {
    expect(causeOfDeath({ ...base, cursed: true, contributions: null })).toBe(
      'Declared dead: its source reports it as deprecated, archived or retired. A known vulnerability affects this version and no fixed version exists.',
    );
    expect(
      causeOfDeath({
        ...base,
        state: 'alive',
        deadReason: null,
        wounded: true,
        contributions: null,
      }),
    ).toBe(
      'Maintained. Upgrade advised: a fixed version exists, a fix is pending, or this version is deprecated.',
    );
  });
  it('says nothing it does not know for a node with no verdict', () => {
    expect(
      causeOfDeath({ ...base, state: 'unscored', deadReason: null, contributions: null }),
    ).toBe('No verdict: there are no scored signals for this version.');
  });
  it('does not claim a declaration for a package that is only Ailing', () => {
    expect(causeOfDeath({ ...base, state: 'ailing', deadReason: null })).toContain(
      'It is not declared dead.',
    );
  });
});
