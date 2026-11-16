"""Offline tests for scripts/heldout_fpool.py calibrate and search (T5.7; MV2-SMP-2).

The `gh` runner and the contents API are fakes; files live under `tmp_path`. No network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "heldout_fpool.py"
TODAY = "2026-11-16"


@pytest.fixture(scope="module")
def script() -> Iterator[Any]:
    spec = importlib.util.spec_from_file_location("heldout_fpool", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["heldout_fpool"] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop("heldout_fpool", None)


# A size inside each band, by band label.
IN_BAND = {
    "<1000": 500,
    "1000..2999": 2000,
    "3000..5999": 4000,
    "6000..11999": 9000,
    ">=12000": 20000,
}


class FakeGh:
    """Fake `gh search code` and `gh api repos/.../contents/...` behind one runner."""

    def __init__(
        self, hits_for: Any = None, sizes: Any = None, fail_cell: str | None = None
    ) -> None:
        self.calls: list[list[str]] = []
        self.hits_for: Any = hits_for or (lambda phrase, filename, band: [])
        self.sizes: Any = sizes or (lambda repo, path: 500)
        self.fail_phrase_band = fail_cell  # "<phrase>|<filename>|<band>" always fails
        self.band_of_path: dict[str, str] = {}

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        assert args[0] == "gh"
        if args[1] == "search":
            phrase = args[3].strip('"')
            band = args[4].removeprefix("size:")
            filename = args[args.index("--filename") + 1]
            assert args[args.index("--limit") + 1] == "100"
            assert args[args.index("--json") + 1] == "repository,path,url"
            if self.fail_phrase_band == f"{phrase}|{filename}|{band}":
                return 1, ""
            hits = self.hits_for(phrase, filename, band)
            return 0, json.dumps(
                [
                    {"repository": {"nameWithOwner": r}, "path": p, "url": f"https://x/{r}/{p}"}
                    for r, p in hits
                ]
            )
        assert args[1] == "api"
        _, _, rest = args[2].partition("repos/")
        repo = "/".join(rest.split("/")[:2])
        path = rest.split("/contents/", 1)[1]
        return 0, json.dumps({"size": self.sizes(repo, path)})

    def searches(self) -> list[list[str]]:
        return [c for c in self.calls if c[1] == "search"]


def calibration_gh(bad_band: str | None = None) -> FakeGh:
    def hits_for(phrase: str, filename: str, band: str) -> list[tuple[str, str]]:
        return [(f"o{i}/r{list(IN_BAND).index(band)}", f"README{i}.md") for i in range(7)]

    def sizes(repo: str, path: str) -> int:
        band = list(IN_BAND)[int(repo.split("/r", 1)[1])]
        if band == bad_band and path == "README3.md":
            return 99999 if band != ">=12000" else 5
        return IN_BAND[band]

    return FakeGh(hits_for, sizes)


def sleeps() -> tuple[list[float], Any]:
    log: list[float] = []
    return log, log.append


def raw(tmp_path: Path) -> Path:
    return tmp_path / "f" / "raw"


def go(script: Any, tmp_path: Path, cmd: str, gh: FakeGh, sleep: Any) -> int:
    return int(script.main(["--heldout-dir", str(tmp_path), cmd], gh, sleep, TODAY))


def calibrate_ok(script: Any, tmp_path: Path) -> None:
    _, sleep = sleeps()
    assert go(script, tmp_path, "calibrate", calibration_gh(), sleep) == 0


def test_calibration_pass_samples_five_per_band(script: Any, tmp_path: Path) -> None:
    gh = calibration_gh()
    assert go(script, tmp_path, "calibrate", gh, lambda s: None) == 0
    rows = (raw(tmp_path) / "calibration.tsv").read_text().splitlines()
    assert rows[0] == "band\trepo\tpath\tsize_bytes\tin_band"
    assert len(rows) == 1 + 5 * 5
    assert all(r.endswith("\ttrue") for r in rows[1:])
    assert script.calibration_passed(raw(tmp_path) / "calibration.tsv")
    # the size qualifier is in the query text, never the gh --size flag
    assert all("--size" not in c for c in gh.calls)
    assert gh.searches()[0][3:5] == ['"feature-complete"', "size:<1000"]


def test_calibration_fail_writes_file_and_blocks_search(
    script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert go(script, tmp_path, "calibrate", calibration_gh("1000..2999"), lambda s: None) == 1
    text = (raw(tmp_path) / "calibration.tsv").read_text()
    assert "\t99999\tfalse" in text
    assert "99999 bytes" in capsys.readouterr().err
    gh = FakeGh()
    assert go(script, tmp_path, "search", gh, lambda s: None) == 1
    assert gh.calls == []
    assert not (raw(tmp_path) / "query-log.tsv").exists()


def test_search_refuses_without_calibration(script: Any, tmp_path: Path) -> None:
    gh = FakeGh()
    assert go(script, tmp_path, "search", gh, lambda s: None) == 1
    assert gh.calls == []


def test_search_logs_zero_and_saturated_cells(script: Any, tmp_path: Path) -> None:
    calibrate_ok(script, tmp_path)

    def hits_for(phrase: str, filename: str, band: str) -> list[tuple[str, str]]:
        if (phrase, filename, band) == ("feature-complete", "README.md", "<1000"):
            return [(f"o{i % 60}/r{i}", "README.md") for i in range(100)]
        if (phrase, filename, band) == ("feature-complete", "README.md", "1000..2999"):
            return [("a/b", "README.md"), ("a/b", "docs/README.md"), ("c/d", "README.md")]
        return []

    gaps, sleep = sleeps()
    assert go(script, tmp_path, "search", FakeGh(hits_for), sleep) == 0
    lines = (raw(tmp_path) / "query-log.tsv").read_text().splitlines()
    assert len(lines) == 201
    rows = {int(c[0]): c for c in (ln.split("\t") for ln in lines[1:])}
    assert rows[1] == [
        "1",
        "feature-complete",
        "README.md",
        "<1000",
        TODAY,
        "100",
        "100",
        "100",
        "true",
        "ok",
    ]
    assert rows[2][5:] == ["3", "2", "100", "false", "ok"]
    assert rows[3][5:] == ["0", "0", "100", "false", "ok"]
    assert (raw(tmp_path) / "repos_3.txt").read_text() == ""
    assert (raw(tmp_path) / "repos_2.txt").read_text() == "a/b\nc/d\n"
    assert gaps.count(7.0) == 199  # 7 s between the 200 searches


def test_resume_skips_completed_cells(script: Any, tmp_path: Path) -> None:
    calibrate_ok(script, tmp_path)
    first = FakeGh(fail_cell="feature-complete|README.md|3000..5999")
    assert go(script, tmp_path, "search", first, lambda s: None) == 1
    second = FakeGh()
    assert go(script, tmp_path, "search", second, lambda s: None) == 0
    assert len(second.searches()) == 198
    assert second.searches()[0][4] == "size:3000..5999"
    lines = (raw(tmp_path) / "query-log.tsv").read_text().splitlines()
    assert [ln.split("\t")[0] for ln in lines[1:]] == [str(i) for i in range(1, 201)]
    third = FakeGh()
    assert go(script, tmp_path, "search", third, lambda s: None) == 0
    assert third.searches() == []


def test_failing_cell_stops_run_after_three_retries_and_is_not_skipped(
    script: Any, tmp_path: Path
) -> None:
    calibrate_ok(script, tmp_path)
    gaps, sleep = sleeps()
    gh = FakeGh(fail_cell="feature-complete|README.md|3000..5999")
    assert go(script, tmp_path, "search", gh, sleep) == 1
    lines = (raw(tmp_path) / "query-log.tsv").read_text().splitlines()
    assert [ln.split("\t")[0] for ln in lines[1:]] == ["1", "2"]
    assert not (raw(tmp_path) / "repos_3.txt").exists()
    failing = [c for c in gh.searches() if c[4] == "size:3000..5999"]
    assert len(failing) == 4  # first try plus 3 retries
    assert len(gh.searches()) == 2 + 4  # nothing after the failing cell
    assert gaps.count(10.0) == 1 and gaps.count(20.0) == 1 and gaps.count(40.0) == 1


def test_log_that_does_not_match_the_grid_stops(script: Any, tmp_path: Path) -> None:
    calibrate_ok(script, tmp_path)
    log = raw(tmp_path) / "query-log.tsv"
    log.write_text(
        "\t".join(script.LOG_HEADER)
        + "\n1\tother phrase\tREADME.md\t<1000\t2026-11-16\t0\t0\t100\tfalse\tok\n"
    )
    gh = FakeGh()
    assert go(script, tmp_path, "search", gh, lambda s: None) == 1
    assert gh.calls == []
