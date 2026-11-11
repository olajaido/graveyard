"""Result and evidence types for the autopsy source clients (design §3).

Every dataclass is frozen. Mappings are read-only ``MappingProxyType`` views.
``Evidence`` and ``SourceWarning`` pass every string through the token-shape
redaction in ``secret.py`` when constructed (SRC-SEC-3), ``Evidence`` also strips any
``user:password@`` from its URLs (``urls.strip_userinfo``), cap ``detail`` at 200
characters (SRC-WARN-3) and sort their collections, so equal inputs give equal
values. This module does no I/O and imports only ``core.scoring.types.Signals``,
``core.sources.secret`` and ``core.sources.urls``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Final, Literal

from core.scoring.types import Signals
from core.sources.secret import redact
from core.sources.urls import strip_userinfo

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

MAX_DETAIL: Final = 200
MAX_INPUT_PURL: Final = 200
_MAX_JSON_DEPTH: Final = 32

# The 11 signal keys, in the order of the anchor fixtures (SRC-API-3).
EVIDENCE_KEYS: Final[tuple[str, ...]] = (
    "s1_declared_death",
    "s1b_version_deprecated",
    "s2_latest_release_at",
    "s3_last_push_at",
    "s4_maintained",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s7_advisories",
    "s8_overall",
    "s9_weekly_downloads",
)

# Closed set of warning codes (SRC-WARN-2).
WARNING_CODES: Final[frozenset[str]] = frozenset(
    {
        "INVALID_INPUT",
        "HOST_NOT_ALLOWED",
        "HTTP_STATUS",
        "TIMEOUT",
        "CONNECT_ERROR",
        "RATE_LIMITED",
        "REDIRECT_REFUSED",
        "RESPONSE_TOO_LARGE",
        "BAD_CONTENT_TYPE",
        "INVALID_JSON",
        "UNEXPECTED_SHAPE",
        "OUT_OF_DOMAIN",
        "VERSION_NOT_FOUND",
        "PAGINATION_TRUNCATED",
        "PAGINATION_ABORTED",
        "TOO_MANY_ADVISORIES",
        "DEADLINE_EXCEEDED",
        "GITHUB_DISABLED",
        "CACHE_ERROR",
        "INTERNAL_ERROR",
    }
)

# Closed set of source names (SRC-WARN-2).
SOURCE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "depsdev",
        "osv",
        "npm_registry",
        "pypi",
        "npm_downloads",
        "pypistats",
        "scorecard",
        "github",
        "cache",
        "internal",
    }
)

ITEM_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {"INVALID_PURL", "MISSING_VERSION", "INVALID_AS_OF"}
)
REPO_VIA_VALUES: Final[frozenset[str]] = frozenset({"depsdev", "registry", "project_urls"})


def _clean_text(text: str, limit: int | None = None) -> str:
    """Redact token shapes first, then truncate, so a cut can never leave half a token."""
    cleaned = redact(text)
    return cleaned if limit is None else cleaned[:limit]


def _clean_url(url: str) -> str:
    """Drop any ``user:password@`` first, then redact token shapes (SRC-SEC-3)."""
    return _clean_text(strip_userinfo(url))


def _clean_json(value: JsonValue, depth: int = 0) -> JsonValue:
    """Return ``value`` with every string (and mapping key) redacted.

    Rejects anything that is not JSON-compatible (SRC-API-3): non-finite floats,
    non-``str`` keys, other types, and nesting deeper than 32 levels. Containers are
    rebuilt only when a string changed, so equal inputs stay equal.
    """
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("Evidence.value is nested too deeply")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Evidence.value must not hold NaN or infinity")
        return value
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        items = [_clean_json(item, depth + 1) for item in value]
        return items if items != value else value
    if isinstance(value, dict):
        out: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Evidence.value mapping keys must be strings")
            out[redact(key)] = _clean_json(item, depth + 1)
        return out if out != value else value
    raise ValueError(f"Evidence.value is not JSON-compatible: {type(value).__name__}")


def _is_utc(moment: datetime) -> bool:
    offset = moment.utcoffset()
    return offset is not None and offset == timedelta(0)


@dataclass(frozen=True)
class Evidence:
    """Where one signal's value came from (SRC-API-3, SRC-API-4)."""

    value: JsonValue
    source_url: str | None
    fetched_at: datetime | None  # tz-aware UTC
    extra_source_urls: tuple[str, ...] = ()  # sorted, unique
    note: str | None = None  # fixed template; no third-party text (D11)

    def __post_init__(self) -> None:
        if self.fetched_at is not None and not _is_utc(self.fetched_at):
            raise ValueError("Evidence.fetched_at must be timezone-aware UTC")
        if self.value is not None and (self.source_url is None or self.fetched_at is None):
            raise ValueError("Evidence with a value needs source_url and fetched_at")
        object.__setattr__(self, "value", _clean_json(self.value))
        if self.source_url is not None:
            object.__setattr__(self, "source_url", _clean_url(self.source_url))
        # Redaction can make two different URLs equal, so uniqueness and "not the primary URL"
        # are decided after cleaning.
        object.__setattr__(
            self,
            "extra_source_urls",
            tuple(sorted({_clean_url(url) for url in self.extra_source_urls} - {self.source_url})),
        )
        if self.note is not None:
            object.__setattr__(self, "note", _clean_text(self.note))


@dataclass(frozen=True)
class SourceWarning:
    """A failure, cap, out-of-domain value or unexpected shape (SRC-WARN-1…3)."""

    code: str  # member of WARNING_CODES
    source: str  # member of SOURCE_NAMES
    signals: tuple[str, ...]  # sorted EVIDENCE_KEYS missing because of this failure
    detail: str  # at most 200 characters; template + validated values only
    status: int | None = None

    def __post_init__(self) -> None:
        if self.code not in WARNING_CODES:
            raise ValueError(f"unknown warning code: {self.code!r}")
        if self.source not in SOURCE_NAMES:
            raise ValueError(f"unknown warning source: {self.source!r}")
        unknown = [key for key in self.signals if key not in EVIDENCE_KEYS]
        if unknown:
            raise ValueError(f"unknown signal keys in warning: {sorted(unknown)!r}")
        object.__setattr__(self, "signals", tuple(sorted(set(self.signals))))
        object.__setattr__(self, "detail", _clean_text(self.detail, MAX_DETAIL))


@dataclass(frozen=True)
class ItemError:
    """A per-item input error (D16, SRC-API-5)."""

    code: Literal["INVALID_PURL", "MISSING_VERSION", "INVALID_AS_OF"]
    detail: str  # fixed template; at most 200 characters

    def __post_init__(self) -> None:
        if self.code not in ITEM_ERROR_CODES:
            raise ValueError(f"unknown item error code: {self.code!r}")
        object.__setattr__(self, "detail", _clean_text(self.detail, MAX_DETAIL))


def _warning_sort_key(warning: SourceWarning) -> tuple[str, str, tuple[str, ...], str, int]:
    status = -1 if warning.status is None else warning.status
    return (warning.code, warning.source, warning.signals, warning.detail, status)


@dataclass(frozen=True)
class SourceResult:
    """The outcome for one input item (SRC-API-2): exactly one of ``signals`` / ``error``."""

    input_purl: str  # truncated to 200 characters
    signals: Signals | None
    error: ItemError | None
    evidence: Mapping[str, Evidence] = field(default_factory=dict)  # read-only after init
    warnings: tuple[SourceWarning, ...] = ()  # sorted, de-duplicated
    repo: str | None = None  # github.com/<Owner>/<Repo>
    repo_via: Literal["depsdev", "registry", "project_urls"] | None = None
    resolved_version: str | None = None
    latest_version: str | None = None

    def __post_init__(self) -> None:
        if (self.signals is None) == (self.error is None):
            raise ValueError("exactly one of signals and error must be set")
        if self.repo_via is not None and self.repo_via not in REPO_VIA_VALUES:
            raise ValueError(f"unknown repo_via: {self.repo_via!r}")
        if self.signals is not None:
            if set(self.evidence) != set(EVIDENCE_KEYS):
                raise ValueError("evidence must hold exactly the 11 EVIDENCE_KEYS")
            ordered = {key: self.evidence[key] for key in EVIDENCE_KEYS}
        else:
            if self.evidence:
                raise ValueError("evidence must be empty when error is set")
            ordered = {}
        object.__setattr__(self, "evidence", MappingProxyType(ordered))
        object.__setattr__(self, "input_purl", _clean_text(self.input_purl, MAX_INPUT_PURL))
        object.__setattr__(
            self, "warnings", tuple(sorted(set(self.warnings), key=_warning_sort_key))
        )


@dataclass(frozen=True)
class SourceStats:
    """Batch counters; ``failures`` feeds the ``SourceErrors{source}`` metric."""

    requests: Mapping[str, int]  # by source name
    failures: Mapping[str, int]  # by source name
    cache_hits: int
    cache_misses: int
    s9_skipped: int  # PyPI packages that could not be Resting (D14)

    def __post_init__(self) -> None:
        for name in ("requests", "failures"):
            counts: Mapping[str, int] = getattr(self, name)
            for source in counts:
                if source not in SOURCE_NAMES:
                    raise ValueError(f"unknown source in {name}: {source!r}")
            object.__setattr__(
                self, name, MappingProxyType({key: counts[key] for key in sorted(counts)})
            )


@dataclass(frozen=True)
class BatchResult:
    """One ``SourceResult`` per input, in input order, plus batch statistics."""

    results: tuple[SourceResult, ...]
    stats: SourceStats

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results))
