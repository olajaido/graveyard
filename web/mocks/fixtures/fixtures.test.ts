import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { hauntedGraves, hauntedScan, lodashCertificate } from './haunted-house';
import {
  emptyScan,
  failedScan,
  manyGraves,
  minimalCertificate,
  partialScan,
  preBScan,
  runningScan,
} from './builders';

const FILES = ['scan.json', 'graves.json', 'grave-lodash.template.json'];

describe('the committed captures', () => {
  it.each(FILES)('%s is a byte for byte copy of design/fixtures/haunted-house', (name) => {
    const copy = readFileSync(resolve(process.cwd(), 'content/haunted-house', name));
    const original = readFileSync(resolve(process.cwd(), '../design/fixtures/haunted-house', name));
    expect(copy.equals(original)).toBe(true);
  });

  it('come from one scan, after group B (they carry services and via)', () => {
    expect(hauntedGraves.scanId).toBe(hauntedScan.scanId);
    expect(hauntedScan.services?.length).toBe(2);
    expect(hauntedGraves.items.some((g) => g.via !== null)).toBe(true);
    expect(lodashCertificate.via).toBe('pkg:npm/gulp-util@3.0.8');
    expect(lodashCertificate.evidenceLinks.map((l) => l.kind)).toEqual([
      'registry',
      'repository',
      'deps_dev',
      'advisory',
    ]);
  });
});

describe('the builders', () => {
  it('make the scans the UI has to cope with', () => {
    expect(runningScan('AUTOPSY', { examined: 5, total: 9 }).progress).toEqual({
      examined: 5,
      total: 9,
    });
    expect(runningScan('GRAPH', { examined: 5, total: 9 }).progress).toBeNull();
    expect(runningScan('QUEUED')).toMatchObject({ status: 'QUEUED', services: null });
    expect(runningScan('FETCH').services).not.toBeNull();
    expect(failedScan('NO_MANIFESTS')).toMatchObject({
      status: 'FAILED',
      error: { code: 'NO_MANIFESTS' },
    });
    expect(emptyScan().counts?.dead).toBe(0);
    expect(partialScan()).toMatchObject({ partial: true, counts: { unscored: 7 } });
    expect(preBScan()).toMatchObject({ services: null, progress: null });
  });
  it('make graves with distinct purls, in priority order', () => {
    const graves = manyGraves(600);
    expect(new Set(graves.map((g) => g.purl)).size).toBe(600);
    expect(graves.map((g) => g.priority)).toEqual(
      [...graves.map((g) => g.priority)].sort((a, b) => b! - a!),
    );
  });
  it('make a certificate with every optional field empty', () => {
    const cert = minimalCertificate(manyGraves(1)[0]!);
    expect(cert).toMatchObject({
      signals: null,
      evidence: null,
      contributions: null,
      examplePaths: [],
      evidenceLinks: [],
    });
  });
});
