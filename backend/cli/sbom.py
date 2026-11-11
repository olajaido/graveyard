"""Reading a CycloneDX SBOM file for ``--sbom`` (CLI-SBOM-1, D5).

The file is read and parsed as JSON, nothing more. Structural CycloneDX checks belong to
``core.graph.build_graph``, whose ``ValueError`` the pipeline turns into a ``CliError``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from cli.errors import CliError

MAX_SBOM_BYTES: Final = 32 * 1024 * 1024
"""Largest SBOM file, or Syft output, that the CLI will read (CLI-SYFT-3, CLI-SBOM-1)."""


def load_sbom(path: Path) -> dict[str, Any]:
    """Read ``path`` as a JSON object. Every failure is a ``CliError`` (exit 3).

    Messages are fixed templates: neither the path nor any file content is echoed.
    """
    try:
        if not path.is_file():
            raise CliError("the --sbom file is not a regular file")
        if path.stat().st_size > MAX_SBOM_BYTES:
            raise CliError("the --sbom file is larger than 32 MiB")
        data = path.read_bytes()
    except OSError:
        raise CliError("could not read the --sbom file") from None
    try:
        document = json.loads(data)
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        raise CliError("the --sbom file is not valid JSON") from None
    if not isinstance(document, dict):
        raise CliError("the --sbom file must hold a JSON object (a CycloneDX document)")
    return document
