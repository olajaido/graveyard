"""Process environment as seen by the CLI (D7). Pure: no I/O, no ``os`` import.

Only ``cli/__main__.py`` reads ``os.environ``; it builds a ``CliEnvironment``
and passes it down.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from core.sources.secret import SecretToken

DEFAULT_CONTACT: Final = "https://github.com/olajaido/graveyard"
DEFAULT_WIDTH: Final = 100
SYFT_ENV_ALLOW: Final = ("PATH", "HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME")
# An unexpanded ``${NAME}`` reference (an MCP config variable the host did not expand) is absent.
_UNEXPANDED: Final = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


@dataclass(frozen=True)
class CliEnvironment:
    token: SecretToken | None
    token_rejected: bool  # GITHUB_TOKEN set to a non-blank, invalid value; value dropped
    contact: str | None  # GRAVEYARD_CONTACT or None
    syft_env: Mapping[str, str]  # allow-listed variables + SYFT_CHECK_FOR_APP_UPDATE=false
    width: int  # terminal columns


def _is_absent(raw: str) -> bool:
    """Blank or an unexpanded ``${NAME}`` reference."""
    stripped = raw.strip()
    return not stripped or _UNEXPANDED.match(stripped) is not None


def environment_from_mapping(variables: Mapping[str, str], width: int) -> CliEnvironment:
    """Build the ``CliEnvironment`` from a mapping (a pure function; tests pass a dict)."""
    token: SecretToken | None = None
    rejected = False
    raw = variables.get("GITHUB_TOKEN")
    # An empty, whitespace-only or unexpanded ``${NAME}`` value is an absent token: GitHub
    # Actions renders an absent secret as "" (CLI-ENV-2). Anything else invalid is rejected.
    if raw is not None and not _is_absent(raw):
        try:
            token = SecretToken(raw)
        except ValueError:  # inner whitespace, control characters or too long
            rejected = True
    contact = variables.get("GRAVEYARD_CONTACT")
    if contact is not None and _is_absent(contact):
        contact = None
    syft_env = {name: variables[name] for name in SYFT_ENV_ALLOW if name in variables}
    syft_env["SYFT_CHECK_FOR_APP_UPDATE"] = "false"
    return CliEnvironment(
        token=token,
        token_rejected=rejected,
        contact=contact,
        syft_env=syft_env,
        width=width,
    )
