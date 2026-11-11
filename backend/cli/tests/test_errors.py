"""Unit tests for cli.errors (CLI-GATE-4)."""

from __future__ import annotations

from cli.errors import EXIT_CODE_TABLE, CliError, ExitCode, ExitRequest, UsageError


def test_codes_are_zero_to_four() -> None:
    assert [int(code) for code in ExitCode] == [0, 1, 2, 3, 4]
    assert [code.name for code in ExitCode] == ["OK", "GATE_TRIPPED", "USAGE", "INPUT", "INTERNAL"]


def test_exit_code_table_has_one_line_per_code() -> None:
    lines = EXIT_CODE_TABLE.splitlines()
    assert len(lines) == len(ExitCode)
    for code, line in zip(ExitCode, lines, strict=True):
        assert line.startswith(f"{int(code)}  ")


def test_exception_codes() -> None:
    assert CliError("x").code == ExitCode.INPUT
    assert UsageError("x").code == ExitCode.USAGE
    assert ExitRequest(0, "text").output == "text"
