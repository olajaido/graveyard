"""Integration tests for scripts/check_heldout_order.py, parts 1 to 3 (checks 1 to 9, --tag).

Every test builds a temporary git repository with fixed identities and dates; git is isolated
from the user's and the real repo's configuration, and no test touches the real repo's tags.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_heldout_order.py"
_spec = importlib.util.spec_from_file_location("check_heldout_order", _SCRIPT)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
sys.modules["check_heldout_order"] = mod
_spec.loader.exec_module(mod)

H = "eval/heldout/"
REQ = ".kiro/specs/mortality-model-v2/requirements.md"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


LOCKED = "backend/core/scoring/score.py"
ANALYSIS_FILES = {
    ".kiro/specs/mortality-model-v2/design.md": "d\n",
    "eval/V1_LOCK.json": json.dumps({"files": {LOCKED: _sha("s = 1\n")}}) + "\n",
    LOCKED: "s = 1\n",
}
FROZEN_FILES = {
    "backend/core/scoring/weights.v1.yaml": "w: 0\n",
    "backend/core/scoring/weights.v2.yaml": "w: 1\n",
    "eval/FROZEN_MODEL.v2.json": '{"files": {}}\n',
    H + "README.md": "r\n",
    H + "dataset.yaml": "d: 1\n",
    H + "gate.yaml": "g: 1\n",
    H + "f/queries.tsv": "id\tphrase\n1\ta\n2\tb\n",
    H + "FROZEN_HARNESS.json": "{}\n",
    H + "AMENDMENTS.md": "# Amendments\n\nNo entries.\n",
}
SEED = "graveyard-mortality-v2-heldout-1"
SNAP = '["a"]\n'
DRAW_FILES = {
    H + "draw/draw.json": json.dumps({"seed": SEED, "draw_date": "2026-11-01"}) + "\n",
    H + "snapshot/s.json": SNAP,
    H + "snapshot/pins.json": json.dumps(
        {"sources": {"s": {"file": "s.json", "trimmed_sha256": _sha(SNAP)}}}
    )
    + "\n",
    H + "f/raw/query-log.tsv": "id\tphrase\n1\ta\n2\tb\n",
}
LABELS = "ecosystem,name,version,label\nnpm,x,1.0,dead\nnpm,y,1.0,dead\n"
ANSWER_FILES = {H + "labelled_packages.csv": LABELS, H + "review/r.tsv": "r\n"}
LOG_HEADER = "\t".join(("ecosystem", "name", "attempt", "form", "failure_class", "as_of", "date"))
AS_OF = "2026-11-05"  # the date of the answer-key commit in _good_history
NOT_CAPTURED_Y = f"npm\ty\t1\tnot_captured\thttp_404\t{AS_OF}\t2026-11-06\n"


def _fixture(as_of: str = AS_OF) -> str:
    return json.dumps({"package": "x", "as_of": as_of}) + "\n"


def _capture_files(as_of: str = AS_OF, log_rows: str = NOT_CAPTURED_Y) -> dict[str, str]:
    return {
        H + "fixtures/npm/x.json": _fixture(as_of),
        H + "capture-log.tsv": LOG_HEADER + "\n" + log_rows,
    }


CAPTURE_FILES = _capture_files()


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


class Repo:
    """A temporary repository whose commits advance one day at a time."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.day = 0
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")

    def git(self, *args: str, env: dict[str, str] | None = None) -> str:
        import os

        done = subprocess.run(
            ["git", "-C", str(self.path), *args],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
        )
        return done.stdout

    def commit(self, files: dict[str, str], message: str = "c") -> str:
        for rel, text in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.day += 1
        stamp = f"2026-11-{self.day:02d}T12:00:00+00:00"
        self.git(
            "commit",
            "-q",
            "-m",
            message,
            env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
        )
        return self.git("rev-parse", "HEAD").strip()

    def tag(self, name: str, rev: str = "HEAD") -> None:
        self.git("tag", "-a", name, "-m", name, rev)

    def tags(self) -> list[str]:
        return self.git("tag", "--list").split()


def _good_history(repo: Repo, upto: str = "mortality-v2-frozen") -> None:
    repo.commit({REQ: "r\n"})
    repo.tag("v2-requirements")
    repo.commit(ANALYSIS_FILES)
    repo.tag("mortality-v2-analysis")
    repo.commit(FROZEN_FILES)
    repo.tag("mortality-v2-frozen")
    if upto == "mortality-v2-frozen":
        return
    repo.commit(DRAW_FILES)
    repo.tag("eval-heldout-draw")
    repo.commit(ANSWER_FILES)
    repo.tag("eval-heldout-answer-key")
    repo.commit(CAPTURE_FILES)
    repo.tag("eval-heldout-capture")


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo")


def _run(repo: Repo, *args: str) -> int:
    return int(mod.main([*args, "--repo", str(repo.path)]))


def test_good_history_passes_verify_all(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _good_history(repo, upto="capture")
    assert _run(repo, "--verify-all") == 0
    assert "FAIL" not in capsys.readouterr().err


def test_good_history_passes_step_before_tagging(repo: Repo) -> None:
    _good_history(repo)
    repo.commit(DRAW_FILES)
    assert _run(repo, "--step", "eval-heldout-draw") == 0


def test_requirements_tag_is_never_created(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit({REQ: "r\n"})
    assert _run(repo, "--step", "v2-requirements", "--tag") == 2
    assert "tag exists; not created by this script" in capsys.readouterr().err
    assert repo.tags() == []


def test_requirements_tag_rejected_even_when_it_exists(repo: Repo) -> None:
    repo.commit({REQ: "r\n"})
    repo.tag("v2-requirements")
    before = repo.git("rev-parse", "v2-requirements").strip()
    assert _run(repo, "--step", "v2-requirements", "--tag") == 2
    assert repo.tags() == ["v2-requirements"]
    assert repo.git("rev-parse", "v2-requirements").strip() == before


def test_tag_flag_needs_step(repo: Repo) -> None:
    repo.commit({REQ: "r\n"})
    assert _run(repo, "--verify-all", "--tag") == 2


def test_tags_out_of_order(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    first = repo.commit(ANALYSIS_FILES)
    repo.commit({REQ: "r\n"})
    repo.tag("v2-requirements")
    repo.tag("mortality-v2-analysis", first)
    assert _run(repo, "--verify-all") == 1
    err = capsys.readouterr().err
    assert "[MV2-ORD-1]" in err and "not an ancestor" in err


def test_later_tag_without_earlier_tag(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit({REQ: "r\n"})
    repo.commit(ANALYSIS_FILES)
    repo.tag("mortality-v2-analysis")
    assert _run(repo, "--verify-all") == 1
    assert "v2-requirements is missing" in capsys.readouterr().err


def test_fixture_added_before_answer_key_tag(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _good_history(repo)
    repo.commit(DRAW_FILES)
    repo.tag("eval-heldout-draw")
    repo.commit(CAPTURE_FILES)  # fixtures arrive before the answer key
    repo.commit(ANSWER_FILES)
    repo.tag("eval-heldout-answer-key")
    repo.commit({H + "fixtures/npm/y.json": "{}\n"})
    repo.tag("eval-heldout-capture")
    assert _run(repo, "--verify-all") == 1
    err = capsys.readouterr().err
    assert "check 3" in err and "eval-heldout-capture" in err


def test_draw_file_at_frozen_tag(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit({REQ: "r\n"})
    repo.tag("v2-requirements")
    repo.commit(ANALYSIS_FILES)
    repo.tag("mortality-v2-analysis")
    repo.commit({**FROZEN_FILES, H + "draw/draw.json": "{}\n"})
    repo.tag("mortality-v2-frozen")
    assert _run(repo, "--verify-all") == 1
    err = capsys.readouterr().err
    assert "[MV2-ORD-2]" in err and "draw/draw.json" in err


def test_amendments_entry_at_frozen_tag(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit({REQ: "r\n"})
    repo.tag("v2-requirements")
    repo.commit(ANALYSIS_FILES)
    repo.tag("mortality-v2-analysis")
    entry = "# Amendments\n\n## 2026-11-20 example\npaths: x\nreason: y\n"
    repo.commit({**FROZEN_FILES, H + "AMENDMENTS.md": entry})
    repo.tag("mortality-v2-frozen")
    assert _run(repo, "--verify-all") == 1
    assert "has an entry" in capsys.readouterr().err


def test_amendments_entry_after_frozen_tag_is_not_check_2(repo: Repo) -> None:
    _good_history(repo)
    repo.commit({H + "AMENDMENTS.md": "# Amendments\n\n## 2026-11-20 e\npaths: x\nreason: y\n"})
    assert _run(repo, "--verify-all") == 0


def test_commit_date_is_utc(repo: Repo) -> None:
    sha = repo.commit({REQ: "r\n"})
    stamp = "2026-11-05T23:30:00-05:00"
    repo.git("commit", "-q", "--amend", "--no-edit", env={"GIT_COMMITTER_DATE": stamp})
    sha = repo.git("rev-parse", "HEAD").strip()
    assert mod.commit_date_utc(repo.path, sha) == datetime(2026, 11, 6, 4, 30, tzinfo=UTC)


def test_first_add_and_ancestor_helpers(repo: Repo) -> None:
    a = repo.commit({"a.txt": "1\n"})
    b = repo.commit({"b.txt": "1\n"})
    repo.commit({"a.txt": "2\n"})
    head = mod.head_commit(repo.path)
    assert mod.first_add_commit(repo.path, head, ["a.txt"]) == a
    assert mod.first_add_commit(repo.path, head, ["nope.txt"]) is None
    assert mod.is_ancestor(repo.path, a, b)
    assert not mod.is_ancestor(repo.path, b, a)


# --- checks 4 and 5 (T5.23) --------------------------------------------------------------

GATE = "backend/eval/gate.py"
METRICS = "backend/eval/metrics.py"
MODEL_FILE = "backend/core/scoring/v2/model.py"
REPORT = "backend/eval/report.py"
A_TEST = "backend/eval/tests/test_gate.py"
AMEND = H + "AMENDMENTS.md"


def _entry(date: str, name: str, paths: str) -> str:
    return f"## {date} {name}\npaths: {paths}\nreason: because\n"


def _b_history(repo: Repo) -> None:
    """Good history to the frozen tag, with harness, model and report files in it."""
    repo.commit({REQ: "r\n"})
    repo.tag("v2-requirements")
    repo.commit(ANALYSIS_FILES)
    repo.tag("mortality-v2-analysis")
    repo.commit(
        {
            **FROZEN_FILES,
            H + "FROZEN_HARNESS.json": json.dumps({"files": {GATE: "x", METRICS: "x"}}),
            "eval/FROZEN_MODEL.v2.json": json.dumps({"files": {MODEL_FILE: "x"}}),
            MODEL_FILE: "m = 1\n",
            GATE: "g = 1\n",
            METRICS: "m = 1\n",
            REPORT: "r = 1\n",
            A_TEST: "t = 1\n",
        }
    )
    repo.tag("mortality-v2-frozen")


def _finish(repo: Repo) -> int:
    repo.commit(DRAW_FILES)
    repo.tag("eval-heldout-draw")
    return _run(repo, "--verify-all")


def test_untouched_after_frozen_passes(repo: Repo) -> None:
    _b_history(repo)
    assert _finish(repo) == 0


@pytest.mark.parametrize(
    "path", [MODEL_FILE, "eval/V1_LOCK.json", H + "gate.yaml", "backend/sources/x.py"]
)
def test_category_a_edit_fails_even_with_amendment(
    repo: Repo, capsys: pytest.CaptureFixture[str], path: str
) -> None:
    _b_history(repo)
    repo.commit({AMEND: FROZEN_FILES[AMEND] + _entry("2026-11-01", "e", path)})
    repo.commit({path: "changed\n"})
    assert _finish(repo) == 1
    err = capsys.readouterr().err
    assert "check 4" in err and path in err and "never amendable" in err


def test_category_b_edit_without_amendment_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _b_history(repo)
    repo.commit({GATE: "g = 2\n"})
    assert _finish(repo) == 1
    err = capsys.readouterr().err
    assert "check 5" in err and "no entry naming it" in err


def test_category_b_amendment_in_same_commit_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _b_history(repo)
    repo.commit({GATE: "g = 2\n", AMEND: FROZEN_FILES[AMEND] + _entry("2026-11-01", "e", GATE)})
    assert _finish(repo) == 1
    assert "strict ancestor" in capsys.readouterr().err


def test_category_b_later_dated_amendment_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _b_history(repo)
    repo.commit({AMEND: FROZEN_FILES[AMEND] + _entry("2026-12-30", "e", GATE)})
    repo.commit({GATE: "g = 2\n"})
    assert _finish(repo) == 1
    assert "after the change" in capsys.readouterr().err


def test_category_b_amendment_for_other_path_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _b_history(repo)
    repo.commit({AMEND: FROZEN_FILES[AMEND] + _entry("2026-11-01", "e", METRICS)})
    repo.commit({GATE: "g = 2\n"})
    assert _finish(repo) == 1
    assert "no entry naming it" in capsys.readouterr().err


def test_category_b_earlier_amendment_passes(repo: Repo) -> None:
    _b_history(repo)
    repo.commit({AMEND: FROZEN_FILES[AMEND] + _entry("2026-11-01", "e", f"{METRICS}, {GATE}")})
    repo.commit({GATE: "g = 2\n"})
    assert _finish(repo) == 0


@pytest.mark.parametrize("how", ["delete", "edit"])
def test_amendments_not_append_only_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str], how: str
) -> None:
    _b_history(repo)
    entry = _entry("2026-11-01", "e", GATE)
    repo.commit({AMEND: FROZEN_FILES[AMEND] + entry})
    repo.commit({GATE: "g = 2\n"})
    if how == "delete":
        repo.commit({AMEND: FROZEN_FILES[AMEND]})
    else:
        repo.commit({AMEND: FROZEN_FILES[AMEND] + entry.replace("because", "reworded")})
    assert _finish(repo) == 1
    assert "append-only" in capsys.readouterr().err


def test_report_and_test_edits_pass_with_notice(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _b_history(repo)
    repo.commit({REPORT: "r = 2\n", A_TEST: "t = 2\n"})
    assert _finish(repo) == 0
    err = capsys.readouterr().err
    assert "NOTICE" in err and REPORT in err and A_TEST in err and "FAIL" not in err


def test_parse_amendments_needs_paths_and_reason() -> None:
    text = (
        "# Amendments\n## Entries\nNone.\n"
        "## 2026-11-20 good\npaths: a.py, b.py\nreason: why\n"
        "## 2026-11-21 no-reason\npaths: a.py\n"
        "## 2026-13-01 bad-date\npaths: a.py\nreason: x\n"
    )
    entries = mod.parse_amendments(text)
    assert [e.name for e in entries] == ["good"]
    assert entries[0].paths == {"a.py", "b.py"}


# --- checks 6 to 9 and --tag (T5.24) -----------------------------------------------------


def _to_answer_key(repo: Repo, draw: dict[str, str] | None = None) -> None:
    _good_history(repo)
    repo.commit(draw or DRAW_FILES)
    repo.tag("eval-heldout-draw")
    repo.commit(ANSWER_FILES)
    repo.tag("eval-heldout-answer-key")


def _capture(repo: Repo, files: dict[str, str] | None = None) -> None:
    repo.commit(files or CAPTURE_FILES)
    repo.tag("eval-heldout-capture")


def _provenance(repo: Repo) -> dict[str, str]:
    def blob(rel: str) -> str:
        return hashlib.sha256((repo.path / rel).read_bytes()).hexdigest()

    root = repo.path / H / "fixtures"
    fixtures = sorted(
        f"{p.relative_to(root).as_posix()}\t{hashlib.sha256(p.read_bytes()).hexdigest()}\n"
        for p in root.rglob("*.json")
    )
    return {
        "labels_sha256": blob(H + "labelled_packages.csv"),
        "fixture_set_sha256": _sha("".join(fixtures)),
        "gate_config_sha256": blob(H + "gate.yaml"),
        "frozen_harness_sha256": blob(H + "FROZEN_HARNESS.json"),
        "amendments_sha256": blob(H + "AMENDMENTS.md"),
    }


def _results(
    repo: Repo,
    tweak: dict[str, str] | None = None,
    v1: dict[str, object | None] | None = None,
    v2: dict[str, object | None] | None = None,
) -> dict[str, str]:
    """Result files as the real runner writes them: per-model weights, null v1 manifest."""

    def blob(rel: str) -> str:
        return hashlib.sha256((repo.path / rel).read_bytes()).hexdigest()

    base = _provenance(repo)
    mine: dict[str, dict[str, object | None]] = {
        "v1": {
            "model_version": "v1",
            "weights_sha256": blob("backend/core/scoring/weights.v1.yaml"),
            "manifest_sha256": None,
        },
        "v2": {
            "model_version": "v2",
            "weights_sha256": blob("backend/core/scoring/weights.v2.yaml"),
            "manifest_sha256": blob("eval/FROZEN_MODEL.v2.json"),
        },
    }
    out: dict[str, str] = {}
    for model, extra in (("v1", v1), ("v2", v2)):
        prov = {**base, **mine[model], **(tweak or {}), **(extra or {})}
        out[f"{H}results.{model}.json"] = json.dumps({"provenance": prov}) + "\n"
    return out


def _full_history(
    repo: Repo,
    tweak: dict[str, str] | None = None,
    v1: dict[str, object | None] | None = None,
    v2: dict[str, object | None] | None = None,
) -> None:
    _to_answer_key(repo)
    _capture(repo)
    repo.commit(_results(repo, tweak, v1, v2))
    repo.tag("eval-heldout-result")


def test_full_good_history_passes(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _full_history(repo)
    assert _run(repo, "--verify-all") == 0
    captured = capsys.readouterr()
    assert "FAIL" not in captured.err
    assert f"result tag commit: {repo.git('rev-parse', 'HEAD').strip()}" in captured.out
    assert "never captured: npm/y" in captured.err


def test_draw_seed_and_date_and_pin(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    bad = dict(DRAW_FILES)
    bad[H + "draw/draw.json"] = json.dumps({"seed": "other", "draw_date": "2027-01-01"})
    bad[H + "snapshot/s.json"] = '["changed"]\n'
    _to_answer_key(repo, bad)
    assert _run(repo, "--verify-all") == 1
    err = capsys.readouterr().err
    assert "seed is not the literal" in err and "is after the" in err and "hash differs" in err


def test_query_log_missing_a_grid_cell(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _to_answer_key(repo, {**DRAW_FILES, H + "f/raw/query-log.tsv": "id\tphrase\n1\ta\n"})
    assert _run(repo, "--verify-all") == 1
    assert "no line for grid cell(s) 2" in capsys.readouterr().err


def test_as_of_four_days_after_freeze_date_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _to_answer_key(repo)
    _capture(
        repo,
        _capture_files(as_of="2026-11-09", log_rows=NOT_CAPTURED_Y.replace(AS_OF, "2026-11-09")),
    )
    assert _run(repo, "--verify-all") == 1
    assert "check 7" in capsys.readouterr().err


def test_as_of_three_days_after_freeze_date_passes(repo: Repo) -> None:
    _to_answer_key(repo)
    _capture(
        repo,
        _capture_files(as_of="2026-11-08", log_rows=NOT_CAPTURED_Y.replace(AS_OF, "2026-11-08")),
    )
    assert _run(repo, "--verify-all") == 0


def test_second_recapture_of_one_row_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    rows = (
        f"npm\tx\t1\trefetch_unavailable\thttp_429\t{AS_OF}\t2026-11-06\n"
        f"npm\tx\t2\tonly\ttimeout\t{AS_OF}\t2026-11-06\n" + NOT_CAPTURED_Y
    )
    _to_answer_key(repo)
    _capture(repo, _capture_files(log_rows=rows))
    assert _run(repo, "--verify-all") == 1
    assert "2 re-captures" in capsys.readouterr().err


def test_single_recapture_passes_and_non_transient_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = f"npm\tx\t1\tonly\thttp_503\t{AS_OF}\t2026-11-06\n" + NOT_CAPTURED_Y
    _to_answer_key(repo)
    _capture(repo, _capture_files(log_rows=ok))
    assert _run(repo, "--verify-all") == 0


def test_non_transient_recapture_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    bad = f"npm\tx\t1\tonly\thttp_404\t{AS_OF}\t2026-11-06\n" + NOT_CAPTURED_Y
    _to_answer_key(repo)
    _capture(repo, _capture_files(log_rows=bad))
    assert _run(repo, "--verify-all") == 1
    assert "is not transient" in capsys.readouterr().err


def test_row_without_fixture_or_log_line_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _to_answer_key(repo)
    _capture(repo, _capture_files(log_rows=""))
    assert _run(repo, "--verify-all") == 1
    assert "npm/y has no fixture" in capsys.readouterr().err


def test_result_file_amended_twice_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _to_answer_key(repo)
    _capture(repo)
    results = _results(repo)
    repo.commit(results)
    repo.commit({H + "results.v1.json": results[H + "results.v1.json"] + " \n"})
    repo.commit({H + "results.v1.json": results[H + "results.v1.json"] + "  \n"})
    repo.tag("eval-heldout-result")
    assert _run(repo, "--verify-all") == 1
    assert "touched by 3 commits" in capsys.readouterr().err


def test_provenance_mismatch_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _full_history(repo, {"labels_sha256": "0" * 64})
    assert _run(repo, "--verify-all") == 1
    err = capsys.readouterr().err
    assert "check 8" in err and "labels_sha256" in err


V2_WEIGHTS_SHA = _sha("w: 1\n")


def _check8(repo: Repo, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = _run(repo, "--verify-all")
    return code, capsys.readouterr().err


def test_v1_result_with_v1_weights_passes(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _full_history(repo)
    code, err = _check8(repo, capsys)
    assert code == 0 and "FAIL" not in err


def test_v1_result_with_v2_weights_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _full_history(repo, v1={"weights_sha256": V2_WEIGHTS_SHA})
    code, err = _check8(repo, capsys)
    assert code == 1 and "check 8" in err and "results.v1.json" in err and "weights_sha256" in err


def test_v1_non_null_manifest_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _full_history(repo, v1={"manifest_sha256": "0" * 64})
    code, err = _check8(repo, capsys)
    assert code == 1 and "check 8" in err and "must be null for v1" in err


def test_v2_null_manifest_passes_with_notice(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _full_history(repo, v2={"manifest_sha256": None})
    code, err = _check8(repo, capsys)
    assert code == 0 and "FAIL" not in err
    assert "NOTICE" in err and "FROZEN_MODEL.v2.json unchanged since mortality-v2-frozen" in err


def test_v2_null_manifest_fails_when_model_changed(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _to_answer_key(repo)
    repo.commit({"eval/FROZEN_MODEL.v2.json": '{"files": {"x": 1}}\n'})
    _capture(repo)
    repo.commit(_results(repo, v2={"manifest_sha256": None}))
    repo.tag("eval-heldout-result")
    code, err = _check8(repo, capsys)
    assert code == 1 and "check 8" in err and "manifest_sha256 is null" in err


def test_v2_wrong_manifest_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _full_history(repo, v2={"manifest_sha256": "0" * 64})
    code, err = _check8(repo, capsys)
    assert code == 1 and "check 8" in err and "manifest_sha256" in err


def test_model_version_not_matching_file_name_fails(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _full_history(repo, v2={"model_version": "v1"})
    code, err = _check8(repo, capsys)
    assert code == 1 and "check 8" in err and "model_version" in err


def test_locked_file_edited_fails(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _good_history(repo)
    repo.commit({LOCKED: "s = 2\n"})
    repo.commit(DRAW_FILES)
    repo.tag("eval-heldout-draw")
    assert _run(repo, "--verify-all") == 1
    err = capsys.readouterr().err
    assert "check 9" in err and LOCKED in err


def test_tag_creates_nothing_on_failure(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    _good_history(repo)
    repo.commit({**DRAW_FILES, H + "draw/draw.json": json.dumps({"seed": "other"})})
    before = repo.tags()
    assert _run(repo, "--step", "eval-heldout-draw", "--tag") == 1
    assert repo.tags() == before
    assert "FAIL" in capsys.readouterr().err


def test_tag_creates_annotated_tag_on_success(repo: Repo) -> None:
    _good_history(repo)
    repo.commit(DRAW_FILES)
    assert _run(repo, "--step", "eval-heldout-draw", "--tag") == 0
    assert "eval-heldout-draw" in repo.tags()
    assert repo.git("cat-file", "-t", "eval-heldout-draw").strip() == "tag"
    assert repo.git("rev-parse", "eval-heldout-draw^{commit}") == repo.git("rev-parse", "HEAD")
    assert _run(repo, "--step", "eval-heldout-draw", "--tag") == 2  # already exists


# --- AMENDMENTS.md parser and check 2 (template, fences, invalid dates) ----------------------

_TEMPLATE = (Path(__file__).resolve().parents[3] / "eval/heldout/AMENDMENTS.md").read_text(
    encoding="utf-8"
)
# The template exactly as committed, so the test stays valid if the file is not edited.
_TEMPLATE_TEXT = """# Harness amendments

Append-only. An entry lists harness files (those in `FROZEN_HARNESS.json`) that change after the `mortality-v2-frozen` tag. The entry is committed before the change commit, and its date is not after the date of that change. Model files, the manifest, `weights.v2.yaml`, the source changes and the held-out configuration (`dataset.yaml`, `gate.yaml`, `f/queries.tsv`) cannot be amended; a change to them is a new model version.

Entry format (not a real entry):

```
## YYYY-MM-DD <name>
paths: <comma-separated harness paths>
reason: <one paragraph: what was wrong, what the change does, why it does not depend on any held-out result>
```

## Entries

None.
"""  # noqa: E501


def _frozen_with(repo: Repo, amendments: str) -> None:
    repo.commit({REQ: "r\n"})
    repo.tag("v2-requirements")
    repo.commit(ANALYSIS_FILES)
    repo.tag("mortality-v2-analysis")
    repo.commit({**FROZEN_FILES, H + "AMENDMENTS.md": amendments})
    repo.tag("mortality-v2-frozen")


def test_template_text_matches_repo_file() -> None:
    assert _TEMPLATE.strip() == _TEMPLATE_TEXT.strip()


def test_template_only_has_zero_entries() -> None:
    headings, problems = mod.scan_amendments(_TEMPLATE_TEXT)
    assert headings == [] and problems == []
    assert mod.parse_amendments(_TEMPLATE_TEXT) == []


def test_template_only_passes_check_2_at_frozen_tag(repo: Repo) -> None:
    _frozen_with(repo, _TEMPLATE_TEXT)
    assert _run(repo, "--verify-all") == 0


def test_one_real_entry_is_one_entry_and_fails_check_2(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _TEMPLATE_TEXT.replace("None.", "## 2026-11-20 real\npaths: x\nreason: y")
    headings, problems = mod.scan_amendments(text)
    assert [h.name for h in headings] == ["real"] and problems == []
    _frozen_with(repo, text)
    assert _run(repo, "--verify-all") == 1
    assert "has an entry" in capsys.readouterr().err


def test_heading_inside_fence_is_ignored() -> None:
    text = "## Entries\n\n```\n## 2026-11-20 fenced\npaths: x\nreason: y\n## 2026-13-45 bad\n```\n"
    assert mod.scan_amendments(text) == ([], [])
    tilde = "~~~\n## 2026-11-20 fenced\n~~~\n"
    assert mod.scan_amendments(tilde) == ([], [])


@pytest.mark.parametrize("heading", ["## 2026-13-45 foo", "## YYYY-MM-DD x", "## 2026-11-20"])
def test_invalid_heading_under_entries_is_rejected(
    repo: Repo, capsys: pytest.CaptureFixture[str], heading: str
) -> None:
    text = f"# A\n\n## Entries\n\n{heading}\npaths: x\nreason: y\n"
    headings, problems = mod.scan_amendments(text)
    assert headings == [] and len(problems) == 1 and heading in problems[0]
    assert mod.parse_amendments(text) == []
    _frozen_with(repo, text)
    assert _run(repo, "--verify-all") == 1
    err = capsys.readouterr().err
    assert "invalid entry heading" in err and "has an entry" not in err


def test_invalid_date_without_entries_heading_is_rejected() -> None:
    headings, problems = mod.scan_amendments("## 2026-13-45 foo\n## 2026-11-20 ok\n")
    assert [h.name for h in headings] == ["ok"] and len(problems) == 1
