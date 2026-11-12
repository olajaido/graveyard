"""Types for parsed install commands (design 4.1 of the ``kiro-power`` spec).

Pure: no I/O. ``Target.purl_text`` is the only place a purl string is built.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.purl import Purl, format_purl, normalise_pypi_name


@dataclass(frozen=True)
class Pinned:
    """An exact version was requested."""

    version: str


@dataclass(frozen=True)
class Latest:
    """No specifier, ``latest``, ``*``, or a lone ``>=V`` / ``>V``: the latest installs (D12)."""


@dataclass(frozen=True)
class Range:
    """Any other range: the installed version may differ from the latest (D12)."""


type Spec = Pinned | Latest | Range


@dataclass(frozen=True)
class Target:
    """One package argument that can be checked."""

    ecosystem: Literal["npm", "pypi"]
    name: str  # registry spelling: "@scope/name" or "name" (npm), PEP 503 normalised (pypi)
    spec: Spec

    def purl_text(self, version: str | None) -> str:
        """Return the canonical purl text for this package, at ``version`` if given.

        Raises ``ValueError`` when ``core.purl`` rejects the name or the version.
        """
        if self.ecosystem == "npm":
            if self.name.startswith("@"):
                namespace, sep, name = self.name.partition("/")
                if not sep:
                    raise ValueError("npm scoped name needs a '/'")
                purl = Purl("npm", namespace, name, version)
            else:
                purl = Purl("npm", None, self.name, version)
        else:
            purl = Purl("pypi", None, normalise_pypi_name(self.name), version)
        return format_purl(purl)


@dataclass(frozen=True)
class RequirementRef:
    """The text after ``-r`` / ``--requirement``, unexpanded; never opened by ``core.install``."""

    path: str


@dataclass(frozen=True)
class ParseResult:
    """The outcome of parsing one command line."""

    targets: tuple[Target, ...] = ()  # first-seen order, de-duplicated, at most 20
    requirement_files: tuple[RequirementRef, ...] = ()  # pip / uv -r only, at most 5
    skipped: int = 0  # package arguments recognised but not checkable
    truncated: bool = False  # more than 20 distinct targets were found
