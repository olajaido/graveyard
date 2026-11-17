"""Offline tests for scripts/heldout_draw.py (mortality-model-v2 T5.5; MV2-POP-4, MV2-SMP-1).

The registry is a fake `fetch` function; files live under `tmp_path`. No network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from eval.tests.draw_support import FakeRegistry, load_script, write_repo, write_snapshots

D = "2026-11-15"
TODAY = date(2026, 11, 20)
NPM = [f"pkg{i}" for i in range(12)] + ["@scope/x", "Bad Name"]
PYPI = [f"Py_Pkg.{i}" for i in range(12)]


@pytest.fixture(scope="module")
def script() -> Iterator[Any]:
    import sys

    module = load_script()
    try:
        yield module
    finally:
        sys.modules.pop("heldout_draw", None)


def setup(tmp_path: Path, name: str) -> tuple[Path, Path]:
    root = tmp_path / name
    write_repo(root)
    heldout = root / "heldout"
    write_snapshots(heldout, NPM, PYPI)
    return root, heldout


def run(
    script: Any, root: Path, heldout: Path, fake: FakeRegistry, budget: int = 3, d: str = D
) -> int:
    argv = [
        "--draw-date",
        d,
        "--heldout-dir",
        str(heldout),
        "--repo-root",
        str(root),
        "--budget",
        str(budget),
    ]
    return int(script.main(argv, fetch=fake, sleep=lambda _s: None, today=TODAY))


def states() -> dict[tuple[str, str], str]:
    return {("npm", f"pkg{i}"): "recent" if i % 2 else "quiet" for i in range(12)}


def test_full_run_writes_outputs(script: Any, tmp_path: Path) -> None:
    root, heldout = setup(tmp_path, "full")
    fake = FakeRegistry(states(), default="quiet")
    assert run(script, root, heldout, fake) == 0
    draw = heldout / "draw"
    cands = (draw / "q-candidates.tsv").read_text().splitlines()
    assert cands[0].startswith("ecosystem\torder\tname")
    assert len(cands) == 1 + 3 + 3
    doc = json.loads((draw / "draw.json").read_text())
    npm = doc["counts"]["npm"]
    assert (npm["snapshot_size"], npm["scoped"], npm["syntax_rejected"]) == (14, 1, 1)
    assert npm["selected"] == 3 and npm["short_of_budget"] is False
    assert doc["seed"] == "graveyard-mortality-v2-heldout-1" and doc["draw_date"] == D
    assert doc["queries_sha256"] is None
    assert (heldout / "exclusions.tsv").is_file()


def test_stop_on_failure_then_resume_equals_uninterrupted(script: Any, tmp_path: Path) -> None:
    root_a, held_a = setup(tmp_path, "whole")
    assert run(script, root_a, held_a, FakeRegistry(states())) == 0

    root_b, held_b = setup(tmp_path, "resumed")
    fake = FakeRegistry(states())
    walked = [c.split("/")[1] for c in _first_calls(script, root_a, held_a)]
    victim = walked[1]  # second npm name in draw order
    fake.failing.add(victim)
    assert run(script, root_b, held_b, fake) == 1
    assert fake.calls.count(f"npm/{victim}") == 4  # first try plus 3 retries
    assert not (held_b / "draw" / "draw.json").exists()
    partial = (held_b / "draw" / "q-examined.tsv").read_text().splitlines()
    assert len(partial) == 1 + 1  # header and the one name before the failure

    fake.failing.clear()
    fake.calls.clear()
    assert run(script, root_b, held_b, fake) == 0
    assert f"npm/{walked[0]}" not in fake.calls  # examined rows are not fetched again
    for name in ("q-examined.tsv", "q-candidates.tsv", "draw.json"):
        assert (held_b / "draw" / name).read_bytes() == (held_a / "draw" / name).read_bytes()


def _first_calls(script: Any, root: Path, heldout: Path) -> list[str]:
    rows = (heldout / "draw" / "q-examined.tsv").read_text().splitlines()[1:]
    return [f"npm/{r.split(chr(9))[2]}" for r in rows if r.startswith("npm")]


def test_short_population_records_short_of_budget(script: Any, tmp_path: Path) -> None:
    root, heldout = setup(tmp_path, "short")
    fake = FakeRegistry({}, default="recent")  # nothing is quiet
    assert run(script, root, heldout, fake, budget=5) == 0
    doc = json.loads((heldout / "draw" / "draw.json").read_text())
    for eco in ("npm", "pypi"):
        c = doc["counts"][eco]
        assert c["short_of_budget"] is True and c["selected"] == 0
        assert (
            c["examined"]
            == c["not_quiet"]
            == c["snapshot_size"] - c["scoped"] - c["syntax_rejected"] - c["excluded"]
        )


def test_404_and_missing_date_are_recorded_and_ineligible(script: Any, tmp_path: Path) -> None:
    root, heldout = setup(tmp_path, "inelig")
    fake = FakeRegistry({}, default="quiet")
    # make every npm name unpublished except the no-date one
    fake.states.update({("npm", f"pkg{i}"): "404" for i in range(12)})
    fake.states[("npm", "pkg3")] = "nodate"
    assert run(script, root, heldout, fake, budget=2) == 0
    doc = json.loads((heldout / "draw" / "draw.json").read_text())
    npm = doc["counts"]["npm"]
    assert npm["unpublished"] == 11 and npm["no_release_date"] == 1 and npm["selected"] == 0
    assert npm["short_of_budget"] is True
    assert doc["counts"]["pypi"]["selected"] == 2


def test_future_draw_date_is_refused_before_any_request(script: Any, tmp_path: Path) -> None:
    root, heldout = setup(tmp_path, "future")
    fake = FakeRegistry({})
    assert run(script, root, heldout, fake, d="2026-11-21") == 1
    assert fake.calls == []
    assert not (heldout / "draw").exists()


def test_resume_with_other_draw_date_is_refused(script: Any, tmp_path: Path) -> None:
    root, heldout = setup(tmp_path, "datechg")
    fake = FakeRegistry({}, default="quiet")
    ordered, _ = script.prepare_order("npm", NPM, frozenset(), script.SEED)
    fake.failing.add(ordered[1])  # the first name is examined and recorded as quiet
    assert run(script, root, heldout, fake) == 1
    fake.failing.clear()
    # At 2020-06-01 a 2020-01-01 release is not quiet, so the stored row disagrees.
    assert run(script, root, heldout, fake, d="2020-06-01") == 1
    assert not (heldout / "draw" / "draw.json").exists()


def test_missing_labelled_key_stops_the_draw(script: Any, tmp_path: Path) -> None:
    root, heldout = setup(tmp_path, "missed")
    (root / "eval/labelled_packages.csv").write_text("ecosystem,name\nnpm,not-excluded\n")
    fake = FakeRegistry({})
    assert run(script, root, heldout, fake) == 1
    assert fake.calls == []


def test_existing_draw_json_is_not_overwritten(script: Any, tmp_path: Path) -> None:
    root, heldout = setup(tmp_path, "twice")
    fake = FakeRegistry({})
    assert run(script, root, heldout, fake) == 0
    before = (heldout / "draw" / "draw.json").read_bytes()
    assert run(script, root, heldout, fake) == 1
    assert (heldout / "draw" / "draw.json").read_bytes() == before


def test_legacy_invalid_names_are_counted_as_syntax_rejected_not_drawn(
    script: Any, tmp_path: Path
) -> None:
    root = tmp_path / "legacy"
    write_repo(root)
    heldout = root / "heldout"
    legacy = ["JSONStream", "Base64", "JSV", "-"]
    write_snapshots(heldout, NPM[:12] + ["@scope/x"] + legacy, PYPI)
    assert run(script, root, heldout, FakeRegistry(states(), default="quiet")) == 0
    doc = json.loads((heldout / "draw" / "draw.json").read_text())
    npm = doc["counts"]["npm"]
    assert (npm["snapshot_size"], npm["scoped"], npm["syntax_rejected"]) == (17, 1, 4)
    drawn = (heldout / "draw" / "q-candidates.tsv").read_text()
    assert not any(f"\t{n}\t" in drawn for n in legacy)


# --- registry response size cap (real make_http_fetch path, httpx.MockTransport) ---
MIB = 1024 * 1024


def _client(body_size: int, hits: list[int] | None = None) -> Any:
    """A client whose transport streams `body_size` bytes of whitespace-padded JSON."""
    import httpx

    head, tail = b'{"info": {"version": "1.0"}, "releases": {}}', b""
    pad = b" " * MIB

    def body() -> Iterator[bytes]:
        left = body_size - len(head)
        yield head
        while left > 0:
            piece = pad[: min(left, MIB)]
            left -= len(piece)
            yield piece
        yield tail

    def handler(request: httpx.Request) -> httpx.Response:
        if hits is not None:
            hits.append(1)
        return httpx.Response(200, content=body())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_response_cap_is_64_mib(script: Any) -> None:
    assert script.MAX_RESPONSE_BYTES == 64 * MIB


def test_7_mb_registry_document_is_accepted(script: Any) -> None:
    from datetime import date

    with _client(7 * MIB) as client:
        registry = script.Registry(
            script.make_http_fetch(client), lambda _s: None, lambda: 0.0, date(2026, 11, 15), "s"
        )
        doc = registry._get("pypi", "ddtrace")
    assert doc == {"info": {"version": "1.0"}, "releases": {}}


def test_response_exactly_at_cap_is_accepted(script: Any) -> None:
    with _client(64 * MIB) as client:
        status, body = script.make_http_fetch(client)("https://pypi.org/pypi/x/json")
    assert (status, len(body)) == (200, 64 * MIB)


def test_response_over_cap_is_rejected_then_draw_stops_after_retries(script: Any) -> None:
    from datetime import date

    url = "https://pypi.org/pypi/x/json"
    with _client(64 * MIB + 1) as client, pytest.raises(script.FetchError, match="size cap"):
        script.make_http_fetch(client)(url)
    hits: list[int] = []
    with _client(64 * MIB + 1, hits) as client:
        registry = script.Registry(
            script.make_http_fetch(client), lambda _s: None, lambda: 0.0, date(2026, 11, 15), "s"
        )
        with pytest.raises(script.DrawStopped, match="size cap"):
            registry._get("pypi", "x")
    assert len(hits) == script.RETRIES + 1
