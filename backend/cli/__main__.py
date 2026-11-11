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
from collections.abc import Mapping
from typing import Final

from cli.app import run
from cli.env import CliEnvironment
from core.sources.secret import SecretToken

DEFAULT_WIDTH: Final = 100
_SYFT_ENV_ALLOW: Final = ("PATH", "HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME")


def _environment(environ: Mapping[str, str], width: int) -> CliEnvironment:
    """Build the ``CliEnvironment`` from a mapping (a pure function; tests pass a dict)."""
    token: SecretToken | None = None
    rejected = False
    raw = environ.get("GITHUB_TOKEN")
    if raw is not None:
        try:
            token = SecretToken(raw)
        except ValueError:  # blank, whitespace, control characters or too long (CLI-ENV-2)
            rejected = True
    contact = environ.get("GRAVEYARD_CONTACT")
    if contact is not None and not contact.strip():
        contact = None
    syft_env = {name: environ[name] for name in _SYFT_ENV_ALLOW if name in environ}
    syft_env["SYFT_CHECK_FOR_APP_UPDATE"] = "false"
    return CliEnvironment(
        token=token,
        token_rejected=rejected,
        contact=contact,
        syft_env=syft_env,
        width=width,
    )


def main() -> None:
    """Console-script entry point."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")  # an odd locale must not turn output into a crash
    columns = shutil.get_terminal_size(fallback=(DEFAULT_WIDTH, 24)).columns
    env = _environment(os.environ, columns)
    sys.exit(run(sys.argv[1:], env=env, out=sys.stdout, err=sys.stderr))


if __name__ == "__main__":
    main()
