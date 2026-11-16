"""Entry point for ``python -m eval``: the harness run, or ``merge`` for staged rows."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from eval.analysis_cmd import run_analysis
from eval.compare_cmd import run_compare
from eval.coverage_cmd import run_coverage
from eval.manifest import run_manifest
from eval.merge import run_merge
from eval.run import run


def dispatch(argv: Sequence[str], *, out: TextIO, err: TextIO) -> int:
    """Route ``merge ...`` and ``analysis ...`` to their runners, the rest to ``run``."""
    args = list(argv)
    if args[:1] == ["analysis"]:
        return run_analysis(args[1:], out=out, err=err)
    if args[:1] == ["compare"]:
        return run_compare(args[1:], out=out, err=err)
    if args[:1] == ["coverage"]:
        return run_coverage(args[1:], out=out, err=err)
    if args[:1] == ["manifest"]:
        return run_manifest(args[1:], out=out, err=err)
    if args[:1] == ["merge"]:
        return run_merge(args[1:], out=out, err=err)
    return run(args, out=out, err=err)


def main() -> None:
    """Wire the process streams, dispatch, and exit with the code."""
    sys.exit(dispatch(sys.argv[1:], out=sys.stdout, err=sys.stderr))


if __name__ == "__main__":
    main()
