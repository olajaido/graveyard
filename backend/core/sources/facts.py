"""Parsed facts that the source clients cache and assemble (design §3).

A fact holds parsed, validated values only, never a response body. Each fact is a
frozen dataclass with:

* ``to_json()``: a plain ``dict`` of JSON values (dates as ``YYYY-MM-DD`` strings,
  tuples as lists), the ``data`` part of a cache item;
* ``from_json(obj)``: the inverse. It returns ``None`` (never raises) when ``obj`` is
  not exactly what ``to_json`` produces: not a mapping, a missing or extra key, a wrong
  type (``bool`` is not an ``int``), or a value outside its domain. A cache entry that
  decodes to ``None`` is treated as a miss (SRC-CACHE-6), so a stale or tampered entry
  can never reach ``assemble``.

Domains, enforced on decode (SRC-SEC-4, SRC-API-6):

* counts are ``int`` >= 0; scores are in [0, 10] or exactly -1 (returned as ``float``);
* dates are ISO ``YYYY-MM-DD`` exactly (not a timestamp, not a basic-format date);
* version strings match ``is_valid_version``; advisory ids match ``is_valid_osv_id``;
* ``OsvVuln.fixed_versions`` is sorted and unique, and ``has_fix`` equals
  ``bool(fixed_versions)``;
* a ``GitHubRepo`` with ``found`` false has no other data, and
  ``committers_lower_bound`` implies ``committers`` is set;
* ``repo_candidates`` hold raw strings in priority order. They are not trusted: the
  consumer reduces each through ``core.purl.normalise_repo_url``, and the cache stores only
  the reduced forms (``reduced_repo_candidates``), never the raw text.

Constructing a fact directly does not validate it; the parsers build facts from values
that already came through ``core.sources.accessors``.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import ClassVar, Final, Self

from core.purl import normalise_repo_url
from core.sources.accessors import (
    as_bool,
    as_date,
    as_int,
    as_list,
    as_mapping,
    as_score,
    as_str,
)
from core.sources.model import JsonValue
from core.sources.urls import is_valid_osv_id

_VERSION: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!~-]{0,99}")


def is_valid_version(value: str) -> bool:
    """True if ``value`` matches ``[A-Za-z0-9][A-Za-z0-9._+!~-]{0,99}`` (SRC-SEC-4)."""
    return _VERSION.fullmatch(value) is not None


def reduced_repo_candidates(candidates: Iterable[str]) -> list[JsonValue]:
    """The repo candidates as the cache stores them: ``github.com/<owner>/<repo>`` only.

    A candidate is a raw string from a response, so its text is untrusted: it can be any
    description-like text, or an echo of a credential. The cache keeps what
    ``normalise_repo_url`` makes of each one, in the same order, and drops a candidate it
    rejects. Repository resolution does exactly that with a raw candidate (SRC-REPO-2) and
    the reduced form is its own fixed point, so a decoded fact resolves to the same
    repository as the fresh one (SRC-SEC-3, SRC-SEC-4).
    """
    out: list[JsonValue] = []
    for raw in candidates:
        reduced = normalise_repo_url(raw)
        if reduced is not None:
            out.append(reduced)
    return out


class _Reject(Exception):
    """Internal: a JSON value is outside a fact's domain. Never leaves this module."""


# --- field decoders: return the value or raise _Reject --------------------------------


def _exact(obj: object, keys: frozenset[str]) -> Mapping[str, object]:
    mapping = as_mapping(obj)
    if mapping is None or set(mapping.keys()) != keys:
        raise _Reject
    return mapping


def _bool(value: object) -> bool:
    result = as_bool(value)
    if result is None:
        raise _Reject
    return result


def _opt_bool(value: object) -> bool | None:
    return None if value is None else _bool(value)


def _opt_count(value: object) -> int | None:
    if value is None:
        return None
    result = as_int(value)
    if result is None:
        raise _Reject
    return result


def _opt_score(value: object) -> float | None:
    if value is None:
        return None
    result = as_score(value)
    if result is None:
        raise _Reject
    return result


def _opt_date(value: object) -> date | None:
    if value is None:
        return None
    text = as_str(value)
    parsed = as_date(text)
    if text is None or parsed is None or parsed.isoformat() != text:
        raise _Reject
    return parsed


def _opt_version(value: object) -> str | None:
    if value is None:
        return None
    text = as_str(value)
    if text is None or not is_valid_version(text):
        raise _Reject
    return text


def _str_list(value: object, valid: Callable[[str], bool] | None = None) -> tuple[str, ...]:
    items = as_list(value)
    if items is None:
        raise _Reject
    out: list[str] = []
    for item in items:
        text = as_str(item)
        if text is None or (valid is not None and not valid(text)):
            raise _Reject
        out.append(text)
    return tuple(out)


def _date_json(value: date | None) -> JsonValue:
    return None if value is None else value.isoformat()


# --- facts -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DepsDevVersion:
    """What deps.dev says about one package version."""

    is_deprecated: bool | None
    published_at: date | None
    repo_candidates: tuple[str, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {"is_deprecated", "published_at", "repo_candidates"}
    )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "is_deprecated": self.is_deprecated,
            "published_at": _date_json(self.published_at),
            "repo_candidates": list(self.repo_candidates),
        }

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(
                is_deprecated=_opt_bool(m["is_deprecated"]),
                published_at=_opt_date(m["published_at"]),
                repo_candidates=_str_list(m["repo_candidates"]),
            )
        except _Reject:
            return None


@dataclass(frozen=True)
class DepsDevPackage:
    """The package document of deps.dev, reduced to the default version (SRC-LAT-1)."""

    default_version: str | None

    _KEYS: ClassVar[frozenset[str]] = frozenset({"default_version"})

    def to_json(self) -> dict[str, JsonValue]:
        return {"default_version": self.default_version}

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(default_version=_opt_version(m["default_version"]))
        except _Reject:
            return None


@dataclass(frozen=True)
class DepsDevProject:
    """Scorecard values from the deps.dev project document (S4, S8)."""

    maintained: float | None
    overall: float | None
    has_scorecard: bool

    _KEYS: ClassVar[frozenset[str]] = frozenset({"maintained", "overall", "has_scorecard"})

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "maintained": self.maintained,
            "overall": self.overall,
            "has_scorecard": self.has_scorecard,
        }

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(
                maintained=_opt_score(m["maintained"]),
                overall=_opt_score(m["overall"]),
                has_scorecard=_bool(m["has_scorecard"]),
            )
        except _Reject:
            return None


@dataclass(frozen=True)
class NpmRegistry:
    """The npm abbreviated packument, reduced (S1, S1b)."""

    latest: str | None
    latest_deprecated: bool | None
    resolved_deprecated: bool | None
    resolved_found: bool

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {"latest", "latest_deprecated", "resolved_deprecated", "resolved_found"}
    )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "latest": self.latest,
            "latest_deprecated": self.latest_deprecated,
            "resolved_deprecated": self.resolved_deprecated,
            "resolved_found": self.resolved_found,
        }

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(
                latest=_opt_version(m["latest"]),
                latest_deprecated=_opt_bool(m["latest_deprecated"]),
                resolved_deprecated=_opt_bool(m["resolved_deprecated"]),
                resolved_found=_bool(m["resolved_found"]),
            )
        except _Reject:
            return None


@dataclass(frozen=True)
class RegistryLatest:
    """The latest version a registry names (npm ``dist-tags.latest``, PyPI ``info.version``)."""

    version: str | None

    _KEYS: ClassVar[frozenset[str]] = frozenset({"version"})

    def to_json(self) -> dict[str, JsonValue]:
        return {"version": self.version}

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(version=_opt_version(m["version"]))
        except _Reject:
            return None


@dataclass(frozen=True)
class NpmFull:
    """The npm full packument, reduced to the fallbacks for S2 and the repo."""

    latest_published: date | None
    repo_candidates: tuple[str, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset({"latest_published", "repo_candidates"})

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "latest_published": _date_json(self.latest_published),
            "repo_candidates": list(self.repo_candidates),
        }

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(
                latest_published=_opt_date(m["latest_published"]),
                repo_candidates=_str_list(m["repo_candidates"]),
            )
        except _Reject:
            return None


@dataclass(frozen=True)
class PypiDoc:
    """The PyPI JSON document, reduced.

    ``resolved_found`` is ``None`` when the document has no ``releases`` key, so the
    existence of the resolved version is unknown. ``repo_candidates`` are label-ordered
    (SRC-REPO-5).
    """

    latest: str | None
    latest_published: date | None
    resolved_found: bool | None
    repo_candidates: tuple[str, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {"latest", "latest_published", "resolved_found", "repo_candidates"}
    )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "latest": self.latest,
            "latest_published": _date_json(self.latest_published),
            "resolved_found": self.resolved_found,
            "repo_candidates": list(self.repo_candidates),
        }

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(
                latest=_opt_version(m["latest"]),
                latest_published=_opt_date(m["latest_published"]),
                resolved_found=_opt_bool(m["resolved_found"]),
                repo_candidates=_str_list(m["repo_candidates"]),
            )
        except _Reject:
            return None


@dataclass(frozen=True)
class Downloads:
    """Weekly downloads (S9). ``weekly`` is ``None`` when the source knows no such package."""

    weekly: int | None

    _KEYS: ClassVar[frozenset[str]] = frozenset({"weekly"})

    def to_json(self) -> dict[str, JsonValue]:
        return {"weekly": self.weekly}

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(weekly=_opt_count(m["weekly"]))
        except _Reject:
            return None


@dataclass(frozen=True)
class OsvIds:
    """Advisory ids that OSV lists for one package version (SRC-OSV-1)."""

    ids: tuple[str, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset({"ids"})

    def to_json(self) -> dict[str, JsonValue]:
        return {"ids": list(self.ids)}

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            return cls(ids=_str_list(m["ids"], is_valid_osv_id))
        except _Reject:
            return None


@dataclass(frozen=True)
class OsvVuln:
    """One OSV advisory, reduced for one package (SRC-OSV-4, SRC-OSV-5)."""

    id: str
    withdrawn: bool
    published_at: date | None
    fixed_versions: tuple[str, ...]
    has_fix: bool

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {"id", "withdrawn", "published_at", "fixed_versions", "has_fix"}
    )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "id": self.id,
            "withdrawn": self.withdrawn,
            "published_at": _date_json(self.published_at),
            "fixed_versions": list(self.fixed_versions),
            "has_fix": self.has_fix,
        }

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            vuln_id = as_str(m["id"])
            if vuln_id is None or not is_valid_osv_id(vuln_id):
                raise _Reject
            fixed = _str_list(m["fixed_versions"], is_valid_version)
            if list(fixed) != sorted(set(fixed)):
                raise _Reject
            has_fix = _bool(m["has_fix"])
            if has_fix != bool(fixed):
                raise _Reject
            return cls(
                id=vuln_id,
                withdrawn=_bool(m["withdrawn"]),
                published_at=_opt_date(m["published_at"]),
                fixed_versions=fixed,
                has_fix=has_fix,
            )
        except _Reject:
            return None


@dataclass(frozen=True)
class GitHubRepo:
    """GitHub data for one repository and one ``as_of`` (S1b archive flag, S3, S5, S6).

    ``found`` is false when GitHub has no such repository; every other field is then
    ``None`` / false.
    """

    is_archived: bool | None
    pushed_at: date | None
    open_issues: int | None
    closed_issues: int | None
    committers: int | None
    committers_lower_bound: bool
    found: bool

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "is_archived",
            "pushed_at",
            "open_issues",
            "closed_issues",
            "committers",
            "committers_lower_bound",
            "found",
        }
    )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "is_archived": self.is_archived,
            "pushed_at": _date_json(self.pushed_at),
            "open_issues": self.open_issues,
            "closed_issues": self.closed_issues,
            "committers": self.committers,
            "committers_lower_bound": self.committers_lower_bound,
            "found": self.found,
        }

    @classmethod
    def from_json(cls, obj: object) -> Self | None:
        try:
            m = _exact(obj, cls._KEYS)
            fact = cls(
                is_archived=_opt_bool(m["is_archived"]),
                pushed_at=_opt_date(m["pushed_at"]),
                open_issues=_opt_count(m["open_issues"]),
                closed_issues=_opt_count(m["closed_issues"]),
                committers=_opt_count(m["committers"]),
                committers_lower_bound=_bool(m["committers_lower_bound"]),
                found=_bool(m["found"]),
            )
            if fact.committers_lower_bound and fact.committers is None:
                raise _Reject
            if not fact.found and (
                fact.is_archived is not None
                or fact.pushed_at is not None
                or fact.open_issues is not None
                or fact.closed_issues is not None
                or fact.committers is not None
                or fact.committers_lower_bound
            ):
                raise _Reject
            return fact
        except _Reject:
            return None
