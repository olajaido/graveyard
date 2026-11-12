"""Entry point for ``python -m cli`` and the ``graveyard`` console script.

This is the only module that reads the process environment (D7, CLI-ENV-1). It builds a
``CliEnvironment`` and hands it to ``app.run``; nothing downstream calls ``os.environ``.
``GITHUB_TOKEN`` is wrapped in a ``SecretToken`` here and is never put in the Syft
environment, argv, a message or a file.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import sys

from cli.app import run
from cli.env import DEFAULT_WIDTH, environment_from_mapping
from cli.stdin import read_hook_payload

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,60}")


def main() -> None:
    """Console-script entry point."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")  # an odd locale must not turn output into a crash
    columns = shutil.get_terminal_size(fallback=(DEFAULT_WIDTH, 24)).columns
    env = environment_from_mapping(os.environ, columns)
    argv = sys.argv[1:]
    if argv[:1] == ["check-install"]:
        try:
            code = run(
                argv,
                env=env,
                out=sys.stdout,
                err=sys.stderr,
                stdin=lambda: read_hook_payload(sys.stdin.buffer),
            )
        except BaseException as exc:  # KPW-CMD-4: nothing may turn into a block or a crash
            if isinstance(exc, SystemExit):
                raise
            name = type(exc).__name__
            name = name if _IDENTIFIER.fullmatch(name) else "Error"
            sys.stdout.write(
                f"graveyard check-install: internal error ({name}); nothing was checked\n"
            )
            code = 0
        sys.exit(code)
    sys.exit(run(argv, env=env, out=sys.stdout, err=sys.stderr))


if __name__ == "__main__":
    main()
