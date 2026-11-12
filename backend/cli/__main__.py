"""Entry point for ``python -m cli`` and the ``graveyard`` console script.

This is the only module that reads the process environment (D7, CLI-ENV-1). It builds a
``CliEnvironment`` and hands it to ``app.run``; nothing downstream calls ``os.environ``.
``GITHUB_TOKEN`` is wrapped in a ``SecretToken`` here and is never put in the Syft
environment, argv, a message or a file.
"""

from __future__ import annotations

import io
import os
import shutil
import sys

from cli.app import run
from cli.env import DEFAULT_WIDTH, environment_from_mapping


def main() -> None:
    """Console-script entry point."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")  # an odd locale must not turn output into a crash
    columns = shutil.get_terminal_size(fallback=(DEFAULT_WIDTH, 24)).columns
    env = environment_from_mapping(os.environ, columns)
    sys.exit(run(sys.argv[1:], env=env, out=sys.stdout, err=sys.stderr))


if __name__ == "__main__":
    main()
