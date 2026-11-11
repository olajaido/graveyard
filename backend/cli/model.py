"""CLI data types (design §4). Pure: no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cli.text import sanitise

WARNING_CODES: frozenset[str] = frozenset(
    {"LOCKFILE_UNREADABLE", "GITHUB_TOKEN_MISSING", "GITHUB_TOKEN_INVALID"}
)
MAX_DETAIL_CHARS = 200


@dataclass(frozen=True)
class ServiceDir:
    path: str  # relative POSIX path, "." for the root
    directory: Path  # absolute
    lockfiles: tuple[str, ...]  # file names, sorted


@dataclass(frozen=True)
class CliWarning:
    code: str  # one of WARNING_CODES
    detail: str  # fixed template; file name and service only
    service: str | None

    def __post_init__(self) -> None:
        if self.code not in WARNING_CODES:
            raise ValueError(f"unknown CLI warning code: {self.code!r}")
        object.__setattr__(self, "detail", sanitise(self.detail[:MAX_DETAIL_CHARS]))

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Total order that tolerates ``service is None``."""
        return (self.service or "", self.code, self.detail)
