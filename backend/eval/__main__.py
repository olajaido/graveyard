"""Entry point for ``python -m eval``: the harness run, or ``merge`` for staged rows."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from eval.merge import run_merge
from eval.run import run


def dispatch(argv: Sequence[str], *, out: TextIO, err: TextIO) -> int:
    """Route ``merge ...`` to ``run_merge`` and everything else to ``run``."""
    args = list(argv)
    if args[:1] == ["merge"]:
        return run_merge(args[1:], out=out, err=err)
    return run(args, out=out, err=err)


def main() -> None:
    """Wire the process streams, dispatch, and exit with the code."""
    sys.exit(dispatch(sys.argv[1:], out=sys.stdout, err=sys.stderr))


if __name__ == "__main__":
    main()
