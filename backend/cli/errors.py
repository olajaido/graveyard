"""Exit codes and CLI exceptions (CLI-GATE-4). Pure: no I/O."""

from __future__ import annotations

from enum import IntEnum
from typing import Final


class ExitCode(IntEnum):
    OK = 0
    GATE_TRIPPED = 1
    USAGE = 2
    INPUT = 3
    INTERNAL = 4


_DESCRIPTIONS: Final[dict[ExitCode, str]] = {
    ExitCode.OK: "the run completed and the gate did not trip",
    ExitCode.GATE_TRIPPED: "the run completed and the gate tripped",
    ExitCode.USAGE: "usage error",
    ExitCode.INPUT: "input or tool error",
    ExitCode.INTERNAL: "internal error",
}

# One line per code, in code order. Used by --help, the README test and the docs.
EXIT_CODE_TABLE: Final[str] = "\n".join(f"{int(code)}  {_DESCRIPTIONS[code]}" for code in ExitCode)


class CliError(Exception):
    """Input or tool error (exit 3). The message is a fixed template."""

    code: ExitCode = ExitCode.INPUT

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(Exception):
    """Usage error (exit 2)."""

    code: ExitCode = ExitCode.USAGE

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ExitRequest(Exception):
    """Raised for --help / --version; carries the exit code and the text to print."""

    def __init__(self, code: int = 0, output: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.output = output
