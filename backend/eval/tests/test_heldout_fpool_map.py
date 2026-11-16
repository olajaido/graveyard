"""Offline tests for scripts/heldout_fpool.py map and build (T5.8; MV2-SMP-2).

The registry and `gh` are fakes; files live under `tmp_path`. No network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "heldout_fpool.py"
SEED = "graveyard-mortality-v2-heldout-1"


@pytest.fixture(scope="module")
def script() -> Iterator[Any]:
    spec = importlib.util.spec_from_file_location("heldout_fpool_map", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["heldout_fpool_map"] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop("heldout_fpool_map", None)


def npm_doc(version: str = "1.0.0", **fields: Any) -> dict[str, Any]:
    return {"version": version, **fields}


def pypi_doc(version: str = "2.0", **info: Any) -> dict[str, Any]:
    return {"info": {"version": version, **info}}


class FakeRegistry:
    def __init__(self, docs: dict[str, Any]) -> None:
        self.docs = docs
        self.urls: list[str] = []

    def __call__(self, url: str) -> tuple[int, bytes]:
        self.urls.append(url)
        doc = self.docs.get(url)
        if doc is None:
            return 404, b""
        return 200, json.dumps(doc).encode()


def write_search_outputs(root: Path, repos_by_cell: dict[int, list[str]]) -> None:
    """A finished search: every grid cell logged, repos files for the given cells."""
    import eval.heldout.fpool as fpool

    raw = root / "f" / "raw"
    raw.mkdir(parents=True)
    header = (
        "id\tphrase\tfilename\tband\trun_date\tfile_hits\tunique_repos\tlimit\tsaturated\tstatus"
    )
    lines = [header]
    for cell in fpool.build_grid():
        repos = repos_by_cell.get(cell.id, [])
        lines.append(
            f"{cell.id}\t{cell.phrase}\t{cell.filename}\t{cell.band}\t2026-11-16\t"
            f"{len(repos)}\t{len(repos)}\t100\tfalse\tok"
        )
        (raw / f"repos_{cell.id}.txt").write_text("".join(f"{r}\n" for r in repos))
    (raw / "query-log.tsv").write_text("\n".join(lines) + "\n")


def run(script: Any, root: Path, cmd: str, fetch: Callable[[str], tuple[int, bytes]]) -> int:
    return int(script.main(["--heldout-dir", str(root), cmd], fetch=fetch, sleep=lambda s: None))


def test_package_pointing_at_longer_repo_does_not_match(script: Any) -> None:
    urls = ["git+https://github.com/foo/bar-baz.git", "https://github.com/foo/bar-baz/issues"]
    assert not script.points_at("foo/bar", urls)
    assert script.points_at("foo/bar-baz", urls)
    # case-folded whole owner/repo; a different owner never matches
    assert script.points_at("Foo/Bar", ["https://github.com/foo/bar"])
    assert not script.points_at("foo/bar", ["https://github.com/other/bar"])
    assert not script.points_at("foo/bar", ["https://evil.com/github.com/foo/bar", "garbage"])


def test_candidate_names(script: Any) -> None:
    names = script.candidate_names("acme/python-widget")
    assert names == ["python-widget", "widget"]
    assert script.candidate_names("acme/pyfoo") == ["pyfoo", "foo"]
    assert script.candidate_names("acme/Foo_Bar") == ["Foo_Bar", "foo-bar"]


def test_scoped_and_invalid_names_are_skipped_and_counted(script: Any, tmp_path: Path) -> None:
    write_search_outputs(tmp_path, {1: ["o/@scoped", "o/Upper"]})
    registry = FakeRegistry({})
    rows, counts = script.run_map(tmp_path / "f" / "raw", registry, lambda s: None)
    assert rows == []
    assert counts["skipped_scoped"] + counts["repositories_unusable"] >= 1
    # npm "Upper" is invalid (uppercase), PyPI "upper" is the PEP 503 form
    assert counts["skipped_invalid"] == 1
    assert not any("%40" in u or "@" in u for u in registry.urls)
    assert "https://registry.npmjs.org/Upper/latest" not in registry.urls
    assert "https://pypi.org/pypi/upper/json" in registry.urls


def test_map_refuses_an_unfinished_search(script: Any, tmp_path: Path) -> None:
    write_search_outputs(tmp_path, {})
    log = tmp_path / "f" / "raw" / "query-log.tsv"
    log.write_text("".join(log.read_text().splitlines(keepends=True)[:-1]))
    assert run(script, tmp_path, "map", FakeRegistry({})) == 1
    assert not (tmp_path / "f" / "raw" / "mapped.tsv").exists()


def test_failing_lookup_stops_and_writes_nothing(script: Any, tmp_path: Path) -> None:
    write_search_outputs(tmp_path, {1: ["foo/bar"]})
    sleeps: list[float] = []

    def broken(url: str) -> tuple[int, bytes]:
        return 503, b""

    assert (
        int(script.main(["--heldout-dir", str(tmp_path), "map"], fetch=broken, sleep=sleeps.append))
        == 1
    )
    assert not (tmp_path / "f" / "raw" / "mapped.tsv").exists()
    assert sleeps.count(script.BACKOFF[0]) >= 1  # retried before stopping


def test_fake_registry_end_to_end_on_a_toy_grid(script: Any, tmp_path: Path) -> None:
    write_search_outputs(
        tmp_path,
        {
            1: ["foo/bar", "foo/bar-baz", "acme/python-widget"],
            2: ["foo/bar-baz", "o1/qpkg", "o1/a", "o1/b", "o1/c", "o1/d"],
        },
    )
    npm = "https://registry.npmjs.org/{}/latest".format
    pypi = "https://pypi.org/pypi/{}/json".format
    registry = FakeRegistry(
        {
            # bar's npm package points at bar-baz: no match for foo/bar
            npm("bar"): npm_doc(repository={"url": "git+https://github.com/foo/bar-baz.git"}),
            pypi("bar"): pypi_doc(project_urls={"Source": "https://github.com/foo/bar"}),
            npm("bar-baz"): npm_doc("3.1.0", repository="git+https://github.com/foo/bar-baz.git"),
            pypi("widget"): pypi_doc("0.4", home_page="https://github.com/Acme/python-widget"),
            npm("qpkg"): npm_doc("9.9.9", bugs={"url": "https://github.com/o1/qpkg/issues"}),
            npm("a"): npm_doc(homepage="https://github.com/o1/a"),
            npm("b"): npm_doc(homepage="https://github.com/o1/b"),
            npm("c"): npm_doc(homepage="https://github.com/o1/c"),
            npm("d"): npm_doc(homepage="https://github.com/o1/d"),
        }
    )
    assert run(script, tmp_path, "map", registry) == 0
    mapped = (tmp_path / "f" / "raw" / "mapped.tsv").read_text().splitlines()
    assert mapped[0] == "query_id\trepo\tecosystem\tname\tversion"
    assert mapped[1:] == [
        "1\tacme/python-widget\tpypi\twidget\t0.4",
        "1\tfoo/bar\tpypi\tbar\t2.0",
        "1\tfoo/bar-baz\tnpm\tbar-baz\t3.1.0",
        "2\to1/a\tnpm\ta\t1.0.0",
        "2\to1/b\tnpm\tb\t1.0.0",
        "2\to1/c\tnpm\tc\t1.0.0",
        "2\to1/d\tnpm\td\t1.0.0",
        "2\to1/qpkg\tnpm\tqpkg\t9.9.9",
    ]
    names = {(r.split("\t")[2], r.split("\t")[3]) for r in mapped[1:]}
    assert ("npm", "bar") not in names  # points at foo/bar-baz
    assert ("pypi", "bar") in names and ("npm", "bar-baz") in names
    assert ("pypi", "widget") in names

    # draw outputs of heldout_draw.py: exclusions, Q candidates and draw.json (Q fields)
    draw = tmp_path / "draw"
    draw.mkdir()
    (tmp_path / "exclusions.tsv").write_text(
        "ecosystem\tname\tsource_file\tsource_kind\nnpm\tqpkg\teval/x.tsv\tpool\n"
    )
    (draw / "q-candidates.tsv").write_text(
        "ecosystem\torder\tname\tlatest_version\treleased_at\tdraw_key\n"
        "npm\t1\tqonly\t5.0.0\t2020-01-01\tk\n"
    )
    q_fields = {"seed": SEED, "draw_date": "2026-11-16", "counts": {"npm": {"selected": 1}}}
    (draw / "draw.json").write_text(json.dumps(q_fields, indent=2, sort_keys=True) + "\n")

    assert run(script, tmp_path, "build", FakeRegistry({})) == 0
    pool = (draw / "f-pool.tsv").read_text().splitlines()
    pool_keys = [tuple(r.split("\t")[1:3]) for r in pool[1:]]
    assert ("npm", "qpkg") not in pool_keys  # excluded
    owners = [r.split("\t")[4] for r in pool[1:]]
    assert owners.count("o1") == 3  # owner cap
    assert len(pool_keys) == len(set(pool_keys)) == len(pool) - 1

    strata = (draw / "strata.tsv").read_text().splitlines()
    assert strata[0] == "ecosystem\tname\tstratum\torder\tlatest_version_at_draw"
    assert strata[1] == "npm\tqonly\tQ\t1\t5.0.0"
    assert all("\tF\t" in r for r in strata[2:]) and len(strata) - 2 == len(pool) - 1

    doc = json.loads((draw / "draw.json").read_text())
    assert {k: doc[k] for k in q_fields} == q_fields  # Q fields untouched
    f_counts = doc["f_counts"]
    assert f_counts["grid_size"] == 200 and f_counts["cells_zero_hits"] == 198
    assert f_counts["unique_repositories"] == 8
    assert f_counts["pool_size"] == len(pool) - 1

    # byte-for-byte rebuild
    before = {p.name: p.read_bytes() for p in draw.iterdir()}
    assert run(script, tmp_path, "build", FakeRegistry({})) == 0
    assert {p.name: p.read_bytes() for p in draw.iterdir()} == before
