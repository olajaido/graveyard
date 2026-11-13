"""Entry point for ``python -m mcp_server`` and the ``graveyard-mcp`` console script.

This is the only module of ``mcp_server`` that reads the process environment (KPW-MCP-7,
D18). It builds a ``CliEnvironment`` with ``cli.env.environment_from_mapping``, picks the
confinement root and runs the server on stdio. It prints nothing: stdout carries the
protocol frames only (KPW-MCP-5).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

from cli.env import DEFAULT_WIDTH, environment_from_mapping
from mcp_server.server import build_server

ROOT_VARIABLE: Final = "GRAVEYARD_MCP_ROOT"
# An unexpanded ``${NAME}`` reference, as in ``cli.env``: the host did not expand it.
_UNEXPANDED: Final = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def resolve_root(raw: str | None, cwd: Path) -> Path:
    """The confinement root: ``raw`` when it names an existing directory, else ``cwd``.

    ``raw`` that is missing, empty, whitespace-only, an unexpanded ``${NAME}`` reference, or
    not an existing directory falls back to ``cwd``. The result is resolved.
    """
    text = (raw or "").strip()
    if text and _UNEXPANDED.fullmatch(text) is None:
        try:
            candidate = Path(text).resolve(strict=True)
            if candidate.is_dir():
                return candidate
        except (OSError, ValueError, RuntimeError):
            pass
    return cwd.resolve()


def main() -> None:
    """Console-script entry point."""
    variables = dict(os.environ)
    env = environment_from_mapping(variables, DEFAULT_WIDTH)
    root = resolve_root(variables.get(ROOT_VARIABLE), Path.cwd())
    build_server(env, root).run(transport="stdio")


if __name__ == "__main__":
    main()
