"""``run``: wiring, streams and exit codes (CLI-CMD-2, CLI-PIPE-8, CLI-JSON-1, CLI-GATE-3…5; D18).

``run`` is the one test seam. It never calls ``sys.exit`` and never touches the process
streams: it writes to the ``out`` and ``err`` it is given and returns the exit code.

Exit codes: 0 clean, 1 gate tripped, 2 usage error, 3 input or tool error, 4 internal
error. Codes 2, 3 and 4 are decided before the gate; the JSON file is written only for
a completed analysis (0 or 1).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC
from pathlib import Path
from typing import TextIO

from cli import check_install
from cli.args import build_parser, parse_args
from cli.env import CliEnvironment
from cli.errors import CliError, ExitCode, ExitRequest, UsageError
from cli.model import Report
from cli.pipeline import Transport, analyse
from cli.render import render_stderr_notes, render_table
from cli.report import report_to_dict
from cli.text import sanitise
from core.sources.clock import Clock
from sources.clock import SystemClock

__all__ = ["run", "write_json"]


def write_json(path: Path, report: Report) -> None:
    """Write the JSON report: UTF-8, ``indent=2``, no NaN, trailing newline (CLI-JSON-1)."""
    text = json.dumps(report_to_dict(report), indent=2, allow_nan=False) + "\n"
    try:
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError:
        raise CliError("could not write the --json file") from None


def run(
    argv: Sequence[str],
    *,
    env: CliEnvironment,
    out: TextIO,
    err: TextIO,
    transport: Transport | None = None,
    clock: Clock | None = None,
    stdin: Callable[[], str | None] | None = None,
) -> int:
    """Run the CLI for ``argv`` and return the exit code."""
    if list(argv[:1]) == ["check-install"]:
        return check_install.run(
            list(argv[1:]), env=env, out=out, err=err, stdin=stdin, transport=transport, clock=clock
        )
    clk: Clock = clock if clock is not None else SystemClock()
    try:
        opts = parse_args(argv, today=clk.now().astimezone(UTC).date())
        report = analyse(opts, env, transport, clk)
        out.write(render_table(report, env.width, opts.show_all))
        err.write(render_stderr_notes(report))
        if opts.json_out is not None:
            write_json(opts.json_out, report)
        return int(report.exit_code)
    except ExitRequest as request:
        (out if request.code == 0 else err).write(request.output)
        return request.code
    except UsageError as error:
        err.write(f"graveyard: error: {sanitise(error.message)}\n{build_parser().format_usage()}")
        return int(ExitCode.USAGE)
    except CliError as error:
        err.write(f"graveyard: error: {sanitise(error.message)}\n")
        return int(ExitCode.INPUT)
    except Exception as exc:
        # The type name only, never the text: it could carry third-party content (CLI-PIPE-8).
        err.write(f"internal error: {sanitise(type(exc).__name__)}\n")
        return int(ExitCode.INTERNAL)
