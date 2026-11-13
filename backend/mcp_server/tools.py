"""The two tool bodies, synchronous and free of MCP types (KPW-MCP-3, D10).

``run_package`` and ``run_project`` do what ``graveyard autopsy --purl PURL --all`` and
``graveyard autopsy PATH --all`` do: parse with ``cli.args.parse_args``, run
``cli.pipeline.analyse`` and return ``report_to_dict`` after ``finish``. Failures are raised
as ``ToolFailure`` with a sanitised one-line message that never carries exception text from
an unexpected error, a path or the token. ``analyse`` calls ``asyncio.run``, so these
functions must run in a worker thread (the server does that).
"""

from __future__ import annotations

from datetime import UTC, date
from pathlib import Path
from typing import Any

from cli.args import parse_args
from cli.env import CliEnvironment
from cli.errors import CliError, UsageError
from cli.pipeline import Transport, analyse
from cli.report import report_to_dict
from cli.text import sanitise
from core.sources.clock import Clock
from mcp_server.output import cap_packages, sanitise_tree
from mcp_server.paths import confine
from sources.clock import SystemClock

__all__ = ["ToolFailure", "finish", "run_package", "run_project", "today"]


class ToolFailure(Exception):
    """A failure the agent should see. ``message`` is sanitised and one line of fixed text."""

    def __init__(self, message: str) -> None:
        clean = sanitise(message)
        super().__init__(clean)
        self.message = clean


def today(clock: Clock) -> date:
    """The current UTC date, as the CLI computes it."""
    return clock.now().astimezone(UTC).date()


def finish(doc: dict[str, Any]) -> dict[str, Any]:
    """Sanitise every string of ``doc`` and apply the size cap with ``truncated``."""
    clean = sanitise_tree(doc)
    assert isinstance(clean, dict)  # sanitise_tree keeps a dict a dict
    return cap_packages(clean)


def _run(
    argv: list[str],
    env: CliEnvironment,
    transport: Transport | None,
    clock: Clock | None,
) -> dict[str, Any]:
    clk: Clock = clock if clock is not None else SystemClock()
    try:
        opts = parse_args(argv, today=today(clk))
        report = analyse(opts, env, transport, clk)
        return finish(report_to_dict(report))
    except (UsageError, CliError) as error:
        raise ToolFailure(error.message) from None
    except Exception as exc:
        # The type name only, never the text: it could carry third-party content or a path.
        raise ToolFailure(f"internal error: {type(exc).__name__}") from None


def run_package(
    purl: str,
    env: CliEnvironment,
    transport: Transport | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Autopsy one package URL (KPW-MCP-3)."""
    return _run(["autopsy", "--purl", purl, "--all"], env, transport, clock)


def run_project(
    path: str,
    root: Path,
    env: CliEnvironment,
    transport: Transport | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Autopsy the project directory ``path``, which must lie inside ``root`` (KPW-MCP-4)."""
    try:
        directory = confine(path, root)
    except ValueError as error:
        raise ToolFailure(str(error)) from None
    return _run(["autopsy", str(directory), "--all"], env, transport, clock)
