"""Process environment as seen by the CLI (D7). Pure: no I/O, no ``os`` import.

Only ``cli/__main__.py`` reads ``os.environ``; it builds a ``CliEnvironment``
and passes it down.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from core.sources.secret import SecretToken

DEFAULT_CONTACT: Final = "https://github.com/olajaido/graveyard"


@dataclass(frozen=True)
class CliEnvironment:
    token: SecretToken | None
    token_rejected: bool  # GITHUB_TOKEN set but not a valid token; value dropped
    contact: str | None  # GRAVEYARD_CONTACT or None
    syft_env: Mapping[str, str]  # allow-listed variables + SYFT_CHECK_FOR_APP_UPDATE=false
    width: int  # terminal columns
