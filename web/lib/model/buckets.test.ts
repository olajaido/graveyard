import { describe, expect, it } from 'vitest';
import { byPriority, rankGraves, WIDTHS } from './buckets';

const g = (n: number, priority: number | null) => ({
  purl: `pkg:npm/p${String(n).padStart(3, '0')}@1`,
  priority,
});

describe('rankGraves', () => {
  it('gives seven graves the buckets 0,0,1,1,2,2,3', () => {
    const graves = [70, 60, 50, 40, 30, 20, 10].map((p, i) => g(i, p));
    const ranks = rankGraves(graves);
    expect(graves.map((x) => ranks.get(x.purl)?.bucket)).toEqual([0, 0, 1, 1, 2, 2, 3]);
    expect(graves.map((x) => ranks.get(x.purl)?.position)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(ranks.get(graves[0]!.purl)?.total).toBe(7);
  });
  it('puts a single grave in the biggest bucket', () => {
    expect(rankGraves([g(1, 5)]).get(g(1, 5).purl)?.bucket).toBe(0);
  });
  it('two graves are the biggest and the third size', () => {
    const r = rankGraves([g(1, 9), g(2, 1)]);
    expect([r.get(g(1, 0).purl)?.bucket, r.get(g(2, 0).purl)?.bucket]).toEqual([0, 2]);
  });
  it('keeps equal priorities in one bucket', () => {
    const graves = [g(1, 90), g(2, 90), g(3, 90), g(4, 90), g(5, 50), g(6, 50), g(7, 50), g(8, 50)];
    const r = rankGraves(graves);
    expect(graves.slice(0, 4).map((x) => r.get(x.purl)?.bucket)).toEqual([0, 0, 0, 0]);
    expect(graves.slice(4).map((x) => r.get(x.purl)?.bucket)).toEqual([2, 2, 2, 2]);
  });
  it('puts a missing priority last and in the smallest bucket', () => {
    const graves = [g(1, null), g(2, 5), g(3, 1)];
    const r = rankGraves(graves);
    expect(r.get(graves[0]!.purl)).toEqual({ position: 3, total: 3, bucket: 3 });
  });
  it('is the same for any input order and uses only four sizes', () => {
    const graves = Array.from({ length: 50 }, (_, i) => g(i, (i * 37) % 11));
    const a = rankGraves(graves);
    const b = rankGraves([...graves].reverse());
    for (const x of graves) expect(b.get(x.purl)).toEqual(a.get(x.purl));
    const buckets = new Set([...a.values()].map((v) => v.bucket));
    expect([...buckets].every((n) => n >= 0 && n <= 3)).toBe(true);
    expect(WIDTHS).toEqual([150, 124, 104, 86]);
  });
  it('sorts by priority, highest first, then by purl', () => {
    const sorted = [g(2, 5), g(1, 5), g(3, 9)].sort(byPriority).map((x) => x.purl);
    expect(sorted).toEqual([g(3, 0).purl, g(1, 0).purl, g(2, 0).purl]);
  });
});
