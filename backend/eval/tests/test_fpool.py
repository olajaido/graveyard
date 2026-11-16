"""F pool grid and build (design 9.1, 9.4; MV2-SMP-2)."""

from __future__ import annotations

from eval.heldout.draw import draw_key, draw_order
from eval.heldout.fpool import (
    BANDS,
    FILENAMES,
    PHRASES,
    MappedRow,
    build_grid,
    build_pool,
    grid_tsv,
    pool_tsv,
)

SEED = "test-seed"


def test_phrases_and_filenames_are_the_design_sets() -> None:
    assert set(PHRASES) == {
        "feature-complete",
        "feature complete",
        "considered complete",
        "complete and stable",
        "stable and complete",
        "is feature complete",
        "considered feature complete",
        "no new features planned",
    }
    assert set(FILENAMES) == {"README.md", "README.rst", "README", "README.txt", "README.markdown"}
    assert [b.label for b in BANDS] == [
        "<1000",
        "1000..2999",
        "3000..5999",
        "6000..11999",
        ">=12000",
    ]


def test_bands_are_disjoint_and_cover_every_integer() -> None:
    for size in [*range(0, 13000), 10**6]:
        assert sum(b.contains(size) for b in BANDS) == 1, size


def test_grid_has_200_unique_rows_with_stable_ids() -> None:
    grid = build_grid()
    assert len(grid) == 200
    assert len({(r.phrase, r.filename, r.band) for r in grid}) == 200
    assert [r.id for r in grid] == list(range(1, 201))
    assert build_grid() == grid
    assert grid_tsv(grid).splitlines()[0] == "id\tphrase\tfilename\tband"


def _row(qid: int, repo: str, eco: str, name: str) -> MappedRow:
    return MappedRow(qid, repo, eco, name, "1.0.0")


def test_dedupe_keeps_lowest_query_id() -> None:
    pool = build_pool(
        [_row(9, "a/x", "npm", "x"), _row(2, "a/x", "npm", "x"), _row(5, "a/x", "npm", "x")],
        [],
        [],
        SEED,
    )
    assert [(p.name, p.query_id) for p in pool] == [("x", 2)]


def test_exclusions_and_q_candidates_removed() -> None:
    mapped = [_row(1, "a/x", "npm", "x"), _row(1, "b/y", "pypi", "y"), _row(1, "c/z", "npm", "z")]
    pool = build_pool(mapped, [("npm", "x")], [("pypi", "y")], SEED)
    assert [(p.ecosystem, p.name) for p in pool] == [("npm", "z")]


def test_owner_cap_applied_in_draw_order() -> None:
    names = [f"pkg{i}" for i in range(6)]
    mapped = [_row(1, "Acme/repo", "npm", n) for n in names] + [_row(1, "other/o", "npm", "solo")]
    pool = build_pool(mapped, [], [], SEED, owner_cap=3)
    order = draw_order(SEED, "F", "npm", [*names, "solo"])
    acme_expected = [n for n in order if n != "solo"][:3]
    assert [p.name for p in pool if p.owner == "acme"] == acme_expected
    assert len(pool) == 4
    assert [p.order for p in pool] == [1, 2, 3, 4]
    assert [p.draw_key for p in pool] == sorted(p.draw_key for p in pool)
    assert all(p.draw_key == draw_key(SEED, "F", p.ecosystem, p.name) for p in pool)


def test_ecosystems_share_one_order() -> None:
    mapped = [_row(1, f"o{i}/r", "npm" if i % 2 else "pypi", f"n{i}") for i in range(10)]
    pool = build_pool(mapped, [], [], SEED)
    assert len(pool) == 10
    assert [p.draw_key for p in pool] == sorted(p.draw_key for p in pool)


def test_rebuild_is_byte_for_byte() -> None:
    mapped = [_row(i % 7, f"o{i % 4}/r{i}", "npm", f"n{i}") for i in range(30)]
    first = pool_tsv(build_pool(mapped, [("npm", "n3")], [("npm", "n4")], SEED))
    second = pool_tsv(build_pool(list(reversed(mapped)), [("npm", "n3")], [("npm", "n4")], SEED))
    assert first == second
    assert first.startswith("order\tecosystem\tname\trepo\towner\tquery_id\tdraw_key\n")
