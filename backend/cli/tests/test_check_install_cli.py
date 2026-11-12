"""Tests for the ``check-install`` command line (T9.3; KPW-CMD-1…5, KPW-PAY-1, KPW-TEST-14…16).

Option parsing, ``--help`` / ``--version``, the exit-code table, the ``autopsy`` exit codes and
epilog, and the "reads nothing / asks nothing" guarantees. No network (the socket guard in
``conftest`` is on, and the transports here fail the test if they are called); fixed clock.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import app
from cli.app import run
from cli.check_install import _gather_targets
from cli.errors import EXIT_CODE_TABLE, ExitCode
from cli.hook import HOOK_EXIT_TABLE, HookExit
from cli.tests.support import FakeClock, make_env, subset_replay_transport
from core.install import HookPayload, RequirementRef
from core.sources.tests import recorded as rec

START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
PROJECT = Path(__file__).resolve().parent / "fixtures" / "anchors-project"
REQUEST = "pkg:npm/request@2.88.2"
NOTE_SUFFIX = "; nothing was checked\n"
NOTE_PREFIX = "graveyard check-install: "


class Result:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err


def _failing_stdin() -> str | None:
    pytest.fail("stdin was read")


def _failing_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"network request made: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def _run(
    *argv: str,
    stdin: Callable[[], str | None] | None = None,
    transport: Any = None,
    env: Any = None,
) -> Result:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        list(argv),
        env=env or make_env(),
        out=out,
        err=err,
        stdin=stdin,
        transport=transport,
        clock=FakeClock(START),
    )
    return Result(code, out.getvalue(), err.getvalue())


def _check(*argv: str) -> Result:
    """``check-install`` with a stdin and a transport that fail the test if used."""
    return _run("check-install", *argv, stdin=_failing_stdin, transport=_failing_transport())


# ------------------------------------------------------------------------ option parsing


@pytest.mark.parametrize("budget", ["0.5", "1", "10", "60", "6e1"])
def test_budget_inside_the_bounds_is_accepted(budget: str) -> None:
    result = _check("ls", "--budget", budget)
    assert (result.code, result.out, result.err) == (0, "", "")


def test_budget_equals_form_is_accepted() -> None:
    result = _check("ls", "--budget=5")
    assert (result.code, result.out, result.err) == (0, "", "")


@pytest.mark.parametrize(
    "budget", ["0.49", "0", "-1", "60.01", "1000", "nan", "inf", "-inf", "abc", "", "1,5"]
)
def test_budget_outside_the_bounds_is_a_note_with_exit_0(budget: str) -> None:
    result = _check("ls", "--budget", budget)
    assert result.code == 0
    assert (
        result.out
        == f"{NOTE_PREFIX}--budget: expected a number of seconds from 0.5 to 60{NOTE_SUFFIX}"
    )
    assert result.err == ""


def test_budget_without_a_value_is_a_note() -> None:
    result = _check("ls", "--budget")
    assert result.code == 0
    assert result.out == f"{NOTE_PREFIX}--budget: a value is required{NOTE_SUFFIX}"


def test_as_of_valid_date_is_accepted() -> None:
    for value in ("2026-11-03", "2026-11-10"):  # a past day and today (the fixed clock)
        result = _check("ls", "--as-of", value)
        assert (result.code, result.out, result.err) == (0, "", "")


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ("2026-11-11", "in the future"),
        ("2999-01-01", "in the future"),
        ("2026-02-30", "not a valid calendar date"),
        ("yesterday", "expected a date as YYYY-MM-DD"),
        ("2026-1-1", "expected a date as YYYY-MM-DD"),
    ],
)
def test_as_of_invalid_or_future_is_a_note_with_exit_0(value: str, fragment: str) -> None:
    result = _check("ls", "--as-of", value)
    assert result.code == 0
    assert result.out.startswith(f"{NOTE_PREFIX}--as-of: ")
    assert fragment in result.out
    assert result.out.endswith(NOTE_SUFFIX)
    assert result.out.count("\n") == 1
    assert result.err == ""


def test_two_commands_are_a_note_with_exit_0() -> None:
    result = _check("npm install a", "npm install b")
    assert (result.code, result.err) == (0, "")
    assert result.out == f"{NOTE_PREFIX}only one COMMAND is allowed{NOTE_SUFFIX}"


@pytest.mark.parametrize("argv", [["--bogus"], ["ls", "--bogus"], ["-x"], ["--budget", "5", "-z"]])
def test_unknown_option_is_a_note_with_exit_0(argv: list[str]) -> None:
    result = _check(*argv)
    assert result.code == 0
    assert result.out == f"{NOTE_PREFIX}unknown option{NOTE_SUFFIX}"
    assert result.err == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["--bogus"],
        ["--budget", "nan"],
        ["--budget"],
        ["--as-of", "2999-01-01"],
        ["a", "b"],
        ["--as-of=nope", "--budget=zzz"],
    ],
)
def test_a_usage_error_never_exits_2(argv: list[str]) -> None:
    result = _check(*argv)
    assert result.code == 0
    assert result.out.startswith(NOTE_PREFIX)
    assert result.out.endswith(NOTE_SUFFIX)


def test_a_command_after_double_dash_may_start_with_a_dash() -> None:
    result = _check("--", "-not-an-option")
    assert (result.code, result.out, result.err) == (0, "", "")


# ----------------------------------------------------------------------- help / version


def test_check_install_help_exits_0_on_stdout() -> None:
    result = _check("--help")
    assert result.code == 0
    assert result.out.startswith("usage: graveyard check-install")
    assert result.err == ""


def test_check_install_short_help_and_version_exit_0() -> None:
    assert _check("-h").out == _check("--help").out
    version = _check("--version")
    assert version.code == 0
    assert version.out.startswith("graveyard ")
    assert version.err == ""


def test_help_wins_over_a_bad_option_before_it() -> None:
    # A token after --help is never parsed; --help returns at once.
    result = _check("--help", "--bogus")
    assert result.code == 0
    assert result.out.startswith("usage: graveyard check-install")


# -------------------------------------------------------------- the exit-code table text


def test_hook_exit_has_only_allow_and_block() -> None:
    assert {int(code) for code in HookExit} == {0, 2}


def test_hook_exit_table_text_is_generated_from_hook_exit() -> None:
    lines = HOOK_EXIT_TABLE.splitlines()
    assert len(lines) == len(HookExit)
    for line, code in zip(lines, HookExit, strict=True):
        number, _, description = line.partition("  ")
        assert number == str(int(code))
        assert description.startswith(code.name.lower() + ":")


def test_check_install_help_contains_the_hook_exit_table() -> None:
    result = _check("--help")
    assert f"exit codes:\n{HOOK_EXIT_TABLE}\n" in result.out
    for code in HookExit:
        assert any(line.startswith(f"{int(code)}  ") for line in result.out.splitlines())


def test_hook_exit_values_match_the_exit_codes_printed_by_help() -> None:
    """Parse the table out of ``check-install --help`` and compare it with ``HookExit``."""
    text = _check("--help").out
    _, header, table = text.partition("exit codes:\n")
    assert header
    documented: dict[int, str] = {}
    for line in table.splitlines():
        number, separator, meaning = line.partition("  ")
        assert separator and number.isdigit() and meaning, f"not a table row: {line!r}"
        assert int(number) not in documented, f"code listed twice: {number}"
        documented[int(number)] = meaning
    assert set(documented) == {int(code) for code in HookExit}
    for code in HookExit:
        assert documented[int(code)].startswith(code.name.lower() + ":")


def test_graveyard_help_lists_check_install_and_both_tables() -> None:
    result = _run("--help")
    assert result.code == 0
    assert "check-install" in result.out
    assert EXIT_CODE_TABLE in result.out
    assert HOOK_EXIT_TABLE in result.out
    assert "exit codes (check-install):\n" + HOOK_EXIT_TABLE in result.out
    assert result.err == ""


# ------------------------------------------------------------ autopsy codes and epilog


def test_autopsy_help_is_unchanged() -> None:
    result = _run("autopsy", "--help")
    assert result.code == 0
    assert result.out.endswith("exit codes:\n" + EXIT_CODE_TABLE + "\n")
    assert HOOK_EXIT_TABLE not in result.out
    assert "check-install" not in result.out


def test_autopsy_exit_0() -> None:
    transport, log = subset_replay_transport(rec.cassette())
    result = _run("autopsy", "--purl", REQUEST, "--as-of", "2026-11-03", transport=transport)
    assert result.code == int(ExitCode.OK)
    assert log.unmatched == []


def test_autopsy_exit_1() -> None:
    transport, _log = subset_replay_transport(rec.cassette())
    result = _run(
        "autopsy", "--purl", REQUEST, "--as-of", "2026-11-03", "--fail-on", "dead",
        transport=transport,
    )  # fmt: skip
    assert result.code == int(ExitCode.GATE_TRIPPED)


def test_autopsy_exit_2() -> None:
    result = _run("autopsy", "--fail-on", "zombie", str(PROJECT))
    assert result.code == int(ExitCode.USAGE)
    assert result.err.startswith("graveyard: error: ")


def test_autopsy_exit_3(tmp_path: Path) -> None:
    result = _run("autopsy", str(PROJECT), "--syft", str(tmp_path / "no-syft"))
    assert result.code == int(ExitCode.INPUT)


def test_autopsy_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("secret-text")

    monkeypatch.setattr(app, "analyse", boom)
    result = _run("autopsy", "--purl", REQUEST)
    assert result.code == int(ExitCode.INTERNAL)
    assert "secret-text" not in result.out + result.err


def test_autopsy_usage_error_is_still_exit_2_not_the_hook_behaviour() -> None:
    result = _run("autopsy", "--bogus")
    assert result.code == 2
    assert result.out == ""


# ----------------------------------------------- COMMAND reads no stdin; no-target payloads


@pytest.mark.parametrize("command", ["ls -la", "npm install", "echo hello", "git status"])
def test_a_command_argument_reads_nothing_from_stdin(command: str) -> None:
    result = _run("check-install", command, stdin=_failing_stdin, transport=_failing_transport())
    assert (result.code, result.out, result.err) == (0, "", "")


def test_usage_notes_and_help_read_nothing_from_stdin() -> None:
    for argv in (["--help"], ["--version"], ["--bogus"], ["--budget", "nan"]):
        assert _check(*argv).code == 0


def _payload(command: object) -> str:
    return json.dumps({"tool_input": {"command": command}, "cwd": "/tmp"})


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "not json",
        "[]",
        "null",
        "{}",
        json.dumps({"tool_input": {}}),
        json.dumps({"tool_input": {"command": 5}}),
        json.dumps({"tool_input": {"command": ""}}),
        _payload("ls -la"),  # not an install
        _payload("npm install"),  # an install with no target
        _payload("npm run build"),
        _payload("pip install --upgrade"),
        _payload("echo hello"),
    ],
)
def test_payloads_with_nothing_to_check_print_nothing_and_make_no_request(
    text: str | None,
) -> None:
    result = _run("check-install", stdin=lambda: text, transport=_failing_transport())
    assert (result.code, result.out, result.err) == (0, "", "")


def test_no_stdin_callable_is_an_empty_payload() -> None:
    result = _run("check-install", stdin=None, transport=_failing_transport())
    assert (result.code, result.out, result.err) == (0, "", "")


# ----------------------------------------------------- the real target count (T10.5)


def test_gather_targets_reports_the_count_before_the_cap(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "".join(f"pkg{i}==1.0.{i}\n" for i in range(25)), encoding="utf-8"
    )
    targets, _notes, truncated, total = _gather_targets(
        HookPayload("pip install -r requirements.txt", str(tmp_path)),
        [RequirementRef("requirements.txt")],
        [],
    )
    assert (len(targets), truncated, total) == (20, True, 25)


def test_gather_targets_total_is_the_plain_count_when_not_capped(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("six==1.17.0\n", encoding="utf-8")
    targets, _notes, truncated, total = _gather_targets(
        HookPayload("pip install -r requirements.txt", str(tmp_path)),
        [RequirementRef("requirements.txt")],
        [],
    )
    assert (len(targets), truncated, total) == (1, False, 1)
