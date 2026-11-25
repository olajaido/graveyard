import { describe, expect, it } from 'vitest';
import { clampProgress, LANTERNS, lanternsFor } from './stage-map';

const scan = (
  status: string,
  stage: string | null,
  progress: { examined: number; total: number } | null = null,
) => ({ status, stage, progress }) as Parameters<typeof lanternsFor>[0];

describe('lanternsFor', () => {
  it('has six lanterns', () => expect(LANTERNS).toHaveLength(6));

  it.each([
    [
      'QUEUED',
      'QUEUED',
      'Waiting for a gravedigger',
      ['waiting', 'waiting', 'waiting', 'waiting', 'waiting', 'waiting'],
    ],
    [
      'RUNNING',
      'VALIDATE',
      'Checking the plot',
      ['working', 'waiting', 'waiting', 'waiting', 'waiting', 'waiting'],
    ],
    [
      'RUNNING',
      'FETCH',
      'Digging up the lockfiles',
      ['done', 'working', 'waiting', 'waiting', 'waiting', 'waiting'],
    ],
    [
      'RUNNING',
      'SBOM',
      'Tagging the bodies',
      ['done', 'done', 'working', 'waiting', 'waiting', 'waiting'],
    ],
    [
      'RUNNING',
      'GRAPH',
      'Tracing the roots',
      ['done', 'done', 'done', 'working', 'waiting', 'waiting'],
    ],
    [
      'RUNNING',
      'AUTOPSY',
      'Examining the bodies',
      ['done', 'done', 'done', 'done', 'working', 'waiting'],
    ],
    ['RUNNING', 'CLASSIFY', 'Pronouncing', ['done', 'done', 'done', 'done', 'done', 'working']],
    ['COMPLETE', 'DONE', 'Exhumation complete', ['done', 'done', 'done', 'done', 'done', 'done']],
  ])('%s %s', (status, stage, text, statuses) => {
    const view = lanternsFor(scan(status, stage));
    expect(view.statuses).toEqual(statuses);
    expect(view.text).toBe(text);
    expect(view.known).toBe(true);
  });

  it('a running scan with no stage yet is queued', () => {
    expect(lanternsFor(scan('RUNNING', null)).text).toBe('Waiting for a gravedigger');
  });

  it('marks the lantern a failed scan stopped at', () => {
    const view = lanternsFor(scan('FAILED', 'GRAPH'));
    expect(view.statuses).toEqual(['done', 'done', 'done', 'stopped', 'waiting', 'waiting']);
    expect(lanternsFor(scan('FAILED', 'QUEUED')).statuses.every((s) => s === 'waiting')).toBe(true);
  });

  it('does not know a stage it has not been taught', () => {
    const view = lanternsFor(scan('RUNNING', 'REPORT'));
    expect(view).toMatchObject({ known: false, text: 'Working…' });
  });

  it('draws the dig depth from the lanterns and the autopsy progress', () => {
    expect(lanternsFor(scan('QUEUED', 'QUEUED')).depth).toBe(0);
    expect(lanternsFor(scan('RUNNING', 'VALIDATE')).depth).toBe(0);
    expect(lanternsFor(scan('RUNNING', 'GRAPH')).depth).toBeCloseTo(3 / 6);
    expect(lanternsFor(scan('RUNNING', 'AUTOPSY', { examined: 0, total: 208 })).depth).toBeCloseTo(
      4 / 6,
    );
    expect(
      lanternsFor(scan('RUNNING', 'AUTOPSY', { examined: 104, total: 208 })).depth,
    ).toBeCloseTo(4.5 / 6);
    expect(
      lanternsFor(scan('RUNNING', 'AUTOPSY', { examined: 208, total: 208 })).depth,
    ).toBeCloseTo(5 / 6);
    expect(lanternsFor(scan('COMPLETE', 'DONE')).depth).toBe(1);
  });

  it('clamps examined to total, and a zero total does not divide by zero', () => {
    expect(clampProgress({ examined: 300, total: 208 })).toEqual({ examined: 208, total: 208 });
    expect(clampProgress({ examined: -1, total: 5 })).toBeNull();
    expect(clampProgress(null)).toBeNull();
    expect(lanternsFor(scan('RUNNING', 'AUTOPSY', { examined: 0, total: 0 })).depth).toBeCloseTo(
      4 / 6,
    );
    expect(lanternsFor(scan('RUNNING', 'AUTOPSY', { examined: 999, total: 10 })).depth).toBeCloseTo(
      5 / 6,
    );
  });
});
