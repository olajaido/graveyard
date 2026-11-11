"""CLI data types (design §4). Pure: no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from cli.args import GateClass
from cli.errors import ExitCode
from cli.text import sanitise
from core.graph import GraphNode, GraphWarning
from core.scoring.types import BaseState, ScoringResult, Signals
from core.sources.model import ItemError, SourceResult, SourceStats

WARNING_CODES: frozenset[str] = frozenset(
    {"LOCKFILE_UNREADABLE", "GITHUB_TOKEN_MISSING", "GITHUB_TOKEN_INVALID", "DIRECT_NOT_IN_SBOM"}
)
TOKEN_WARNING_CODES: frozenset[str] = frozenset({"GITHUB_TOKEN_MISSING", "GITHUB_TOKEN_INVALID"})
MAX_DETAIL_CHARS = 200
MAX_SUBJECTS = 20
"""Most subjects kept on a ``CliWarning``; the count is in the detail (CLI-AUG-5)."""

InputMode = Literal["syft", "sbom", "purl"]


SOURCE_LABELS: dict[str, str] = {
    "github": "GitHub",
    "scorecard": "Scorecard",
    "depsdev": "deps.dev",
    "osv": "OSV",
    "npm_registry": "npm registry",
    "pypi": "PyPI",
    "npm_downloads": "npm downloads",
    "pypistats": "pypistats",
}
"""Display names of the sources, for the table (CLI-EVID-5). Others show their raw name."""


def unverified_text(sources: tuple[str, ...]) -> str:
    """``github data unavailable`` / ``depsdev, github data unavailable`` (CLI-EVID-7).

    The long form kept in the JSON ``unverified_reason``; it uses the raw source names.
    """
    return f"{', '.join(sources)} data unavailable"


def unverified_short(sources: tuple[str, ...]) -> str:
    """``no GitHub data`` / ``no GitHub and Scorecard data``: the form that fits the table."""
    labels = [SOURCE_LABELS.get(name, name) for name in sources]
    joined = labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} and {labels[-1]}"
    return f"no {joined} data"


@dataclass(frozen=True)
class ServiceDir:
    path: str  # relative POSIX path, "." for the root
    directory: Path  # absolute
    lockfiles: tuple[str, ...]  # file names, sorted


@dataclass(frozen=True)
class CliWarning:
    code: str  # one of WARNING_CODES
    detail: str  # fixed template; file name, service and counts only
    service: str | None
    subjects: tuple[str, ...] = ()  # sorted, unique, at most MAX_SUBJECTS (package keys)

    def __post_init__(self) -> None:
        if self.code not in WARNING_CODES:
            raise ValueError(f"unknown CLI warning code: {self.code!r}")
        object.__setattr__(self, "detail", sanitise(self.detail[:MAX_DETAIL_CHARS]))
        subjects = sorted({sanitise(s[:MAX_DETAIL_CHARS]) for s in self.subjects})
        object.__setattr__(self, "subjects", tuple(subjects[:MAX_SUBJECTS]))

    @property
    def sort_key(self) -> tuple[str, str, str, tuple[str, ...]]:
        """Total order that tolerates ``service is None``."""
        return (self.service or "", self.code, self.detail, self.subjects)


@dataclass(frozen=True)
class Row:
    """One ranked package."""

    rank: int  # 1-based position in `sort_results` order
    node: GraphNode | None  # None in --purl mode (no graph)
    source: SourceResult  # evidence, warnings, repo, versions
    scoring: ScoringResult
    signals: Signals  # the signals actually scored (exposure set in project mode)
    why: str
    unverified: tuple[str, ...] = ()  # sources whose skipped or failed data left it unverified

    @property
    def gate_eligible(self) -> bool:
        """False for a Dead-by-score package whose score rests on missing data (CLI-EVID-1)."""
        return not self.unverified

    @property
    def unverified_reason(self) -> str | None:
        return unverified_text(self.unverified) if self.unverified else None


@dataclass(frozen=True)
class Report:
    """Everything the table, the JSON file, the notes and the exit code are made from."""

    as_of: date
    input_mode: InputMode
    syft_version: str | None
    services: tuple[str, ...]  # sorted service paths; empty in --purl mode
    lockfiles: tuple[tuple[str, str, bool], ...]  # (service, file, used)
    model_version: str | None  # None only when no package was scored
    rows: tuple[Row, ...]  # rank order
    item_errors: tuple[tuple[str, ItemError], ...]  # (purl, error)
    graph_warnings: tuple[GraphWarning, ...]
    cli_warnings: tuple[CliWarning, ...]
    stats: SourceStats
    fail_on: frozenset[GateClass]
    matches: tuple[str, ...]  # purls that match fail_on, in rank order
    exit_code: ExitCode  # OK or GATE_TRIPPED
    direct_edges_added: int = 0  # root -> direct edges added from the lockfiles (CLI-AUG-6)

    @property
    def unverified_count(self) -> int:
        return sum(1 for row in self.rows if not row.gate_eligible)

    @property
    def unknown_count(self) -> int:
        return sum(1 for row in self.rows if row.scoring.base_state is BaseState.UNKNOWN)

    @property
    def degraded(self) -> bool:
        """True when any source warning or token warning exists (CLI-JSON-6)."""
        return any(row.source.warnings for row in self.rows) or any(
            w.code in TOKEN_WARNING_CODES for w in self.cli_warnings
        )
