"""Tests for ``cli.app.run`` (T8.3; CLI-CMD-2, CLI-PIPE-8, CLI-JSON-1, CLI-GATE-3…5).

The full project scenario is T9; here the exit-code mapping, the streams and the JSON file
rules are checked with the smallest runs that exercise them (single-package mode over the
cassette, a failing stub Syft, a patched ``analyse``).
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cli import app
from cli.app import run
from cli.errors import EXIT_CODE_TABLE
from cli.tests.support import FakeClock, make_env, make_stub_syft, subset_replay_transport
from core.sources.tests import recorded as rec

PROJECT = Path(__file__).resolve().parent / "fixtures" / "anchors-project"
START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
REQUEST = "pkg:npm/request@2.88.2"


class Result:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err


def _run(*argv: str, transport: Any = None, env: Any = None) -> Result:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        list(argv),
        env=env or make_env(),
        out=out,
        err=err,
        transport=transport,
        clock=FakeClock(START),
    )
    return Result(code, out.getvalue(), err.getvalue())


# ------------------------------------------------------------------------- help / version


def test_version_goes_to_stdout_and_exits_zero() -> None:
    result = _run("--version")
    assert result.code == 0
    assert result.out.startswith("graveyard ")
    assert result.err == ""


@pytest.mark.parametrize("argv", [["--help"], ["autopsy", "--help"]])
def test_help_goes_to_stdout_and_shows_the_exit_code_table(argv: list[str]) -> None:
    result = _run(*argv)
    assert result.code == 0
    assert "usage:" in result.out
    assert EXIT_CODE_TABLE in result.out
    assert result.err == ""


def test_run_without_a_clock_argument_works() -> None:
    out, err = io.StringIO(), io.StringIO()
    assert run(["--version"], env=make_env(), out=out, err=err) == 0


# ------------------------------------------------------------------------------ exit 2


def test_usage_error_is_exit_2_with_one_line_and_the_usage(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    result = _run("autopsy", "--fail-on", "zombie", str(PROJECT), "--json", str(report))
    assert result.code == 2
    assert result.out == ""
    lines = result.err.splitlines()
    assert lines[0].startswith("graveyard: error: --fail-on")
    assert any(line.startswith("usage:") for line in lines)
    assert not report.exists()
    assert "Traceback" not in result.err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["autopsy"],
        ["autopsy", "/definitely/not/a/directory"],
        ["autopsy", "--purl", "not-a-purl"],
        ["autopsy", "--purl", REQUEST, str(PROJECT)],
        ["autopsy", str(PROJECT), "--as-of", "2999-01-01"],
        ["autopsy", str(PROJECT), "--bogus"],
    ],
)
def test_usage_errors(argv: list[str]) -> None:
    result = _run(*argv)
    assert result.code == 2
    assert result.out == ""


# ------------------------------------------------------------------------------ exit 3


def test_a_failing_syft_is_exit_3_with_nothing_on_stdout(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, mode="fail")
    report = tmp_path / "report.json"
    result = _run("autopsy", str(PROJECT), "--syft", str(stub.path), "--json", str(report))
    assert result.code == 3
    assert result.out == ""
    assert result.err.startswith("graveyard: error: Syft failed for service ")
    assert "STUB-SYFT-SECRET-STDERR" not in result.err
    assert not report.exists()


def test_a_missing_syft_is_exit_3(tmp_path: Path) -> None:
    result = _run("autopsy", str(PROJECT), "--syft", str(tmp_path / "no-syft"))
    assert result.code == 3
    assert "--sbom" in result.err


def test_json_into_a_missing_directory_is_exit_3_after_the_table_was_printed(
    tmp_path: Path,
) -> None:
    transport, _log = subset_replay_transport(rec.cassette())
    target = tmp_path / "no-such-dir" / "report.json"
    result = _run(
        "autopsy", "--purl", REQUEST, "--as-of", "2026-11-03", "--json", str(target),
        transport=transport,
    )  # fmt: skip
    assert result.code == 3
    assert "npm request@2.88.2" in result.out
    assert result.err.rstrip().endswith("could not write the --json file")
    assert "no-such-dir" not in result.err  # the path is not echoed


# ------------------------------------------------------------------------------ exit 4


def test_internal_error_names_the_type_and_never_the_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("do-not-print-this")

    monkeypatch.setattr(app, "analyse", boom)
    result = _run("autopsy", "--purl", REQUEST)
    assert result.code == 4
    assert result.err == "internal error: RuntimeError\n"
    assert "do-not-print-this" not in result.err + result.out
    assert result.out == ""


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), SystemExit(5)])
def test_base_exceptions_are_not_caught(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise exc

    monkeypatch.setattr(app, "analyse", boom)
    with pytest.raises(type(exc)):
        _run("autopsy", "--purl", REQUEST)


# ------------------------------------------------------------------- the JSON file (0 or 1)


def test_the_json_file_is_written_when_the_gate_trips(tmp_path: Path) -> None:
    transport, log = subset_replay_transport(rec.cassette())
    target = tmp_path / "report.json"
    result = _run(
        "autopsy", "--purl", REQUEST, "--as-of", "2026-11-03", "--fail-on", "dead",
        "--json", str(target), transport=transport,
    )  # fmt: skip
    assert result.code == 1
    assert log.unmatched == []
    text = target.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    document = json.loads(text)
    assert document["summary"]["exit_code"] == 1
    assert document["summary"]["gate"]["tripped"] is True
    assert document["input"]["mode"] == "purl"
    assert f"gate: 1 package matches --fail-on dead: {REQUEST}\n" in result.err


def test_the_json_file_is_written_when_the_gate_does_not_trip(tmp_path: Path) -> None:
    transport, _log = subset_replay_transport(rec.cassette())
    target = tmp_path / "report.json"
    result = _run(
        "autopsy", "--purl", REQUEST, "--as-of", "2026-11-03", "--json", str(target),
        transport=transport,
    )  # fmt: skip
    assert result.code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["summary"]["exit_code"] == 0
