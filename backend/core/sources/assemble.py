"""Signal assembly: facts in, ``Signals`` + evidence + warnings out (design §9; SRC-S1..S9).

``assemble`` combines the parsed facts of one package into a ``Signals`` value, one
``Evidence`` per signal and the ``SourceWarning`` tuple. The session calls it twice
(design §1): once with S9 ``Deferred`` for PyPI, once with the pypistats result. It is a
port of the prototype's ``combine_s1``, ``assemble``, ``collect_scorecard`` and
``capture_phase1`` with the I/O removed.

Rules, in the order they matter:

* **Kleene logic (D5).** ``k_not``, ``k_and`` and ``k_or`` over ``True`` / ``False`` /
  ``None``. S1 is ``k_or`` of the parts, S1b is ``k_and(resolved_deprecated,
  k_not(latest_deprecated))``. A failure can only turn a signal into ``None``.
* **Chains (§9.2).** Latest version: registry, then the deps.dev package ``isDefault``.
  S2: deps.dev (latest) -> npm full packument / PyPI document. S4 and S8: the deps.dev
  project document, else the Scorecard API document; both values always come from the
  same document. S3, S5, S6: the GitHub fact of the package's repo. S7: OSV. S9: the
  downloads state.
* **Domain guard (§9.3, SRC-API-6).** Facts are not trusted to be in domain (they can be
  built directly). Every count, score, flag, date and advisory is checked on its way in.
  A wrong type is ``UNEXPECTED_SHAPE``, a right type outside the domain is
  ``OUT_OF_DOMAIN``; either way the value becomes ``None`` and a fallback may rescue it.
  The ``Signals(...)`` call is wrapped in ``try/except ValueError`` with a re-validation
  pass, which the guard should make unreachable (SRC-TEST-5).
* **Notes and warnings (§9.4, D11).** Notes are fixed strings. No response text reaches an
  ``Evidence`` or a ``SourceWarning``. A ``Failure(code, source, status, feeds)`` becomes a
  warning whose ``signals`` are ``feeds`` that ended up missing, so a failure rescued by a
  fallback still yields a warning with ``signals=()``.
* **Evidence invariants (SRC-API-3).** Exactly the 11 ``EVIDENCE_KEYS``; a value implies
  ``source_url`` and ``fetched_at``; a missing value has a note.

Derived warnings: ``VERSION_NOT_FOUND`` (the registry lists versions and the resolved one is
not among them: the registry-derived S1/S1b parts are not used, SRC-WARN-5) and
``PAGINATION_TRUNCATED`` (S5 is a lower bound) come from the facts, so clients must not
report them again.

Output is deterministic and sorted: it does not depend on the order of ``failures``.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Final, Literal

from core.purl import Purl, format_purl
from core.scoring.types import Advisory, Signals
from core.sources.accessors import as_bool, as_int, as_score
from core.sources.facts import (
    DepsDevPackage,
    DepsDevProject,
    DepsDevVersion,
    Downloads,
    GitHubRepo,
    NpmFull,
    NpmRegistry,
    OsvVuln,
    PypiDoc,
    is_valid_version,
)
from core.sources.model import (
    EVIDENCE_KEYS,
    SOURCE_NAMES,
    WARNING_CODES,
    Evidence,
    JsonValue,
    SourceWarning,
)
from core.sources.repo_resolve import RepoVia
from core.sources.urls import is_valid_osv_id

# --- keys, feeds and notes ------------------------------------------------------------

_S1: Final = "s1_declared_death"
_S1B: Final = "s1b_version_deprecated"
_S2: Final = "s2_latest_release_at"
_S3: Final = "s3_last_push_at"
_S4: Final = "s4_maintained"
_S5: Final = "s5_committers"
_S6O: Final = "s6_open_issues"
_S6C: Final = "s6_closed_issues"
_S7: Final = "s7_advisories"
_S8: Final = "s8_overall"
_S9: Final = "s9_weekly_downloads"

FEEDS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "depsdev_resolved": (_S1B,),
        "depsdev_latest": (_S1, _S1B, _S2),
        "depsdev_package": (_S1, _S1B, _S2),
        "depsdev_project": (_S4, _S8),
        "scorecard": (_S4, _S8),
        "npm_registry": (_S1, _S1B),
        "pypi": (_S2,),
        "npm_full": (_S2,),
        "osv": (_S7,),
        "github": (_S1, _S3, _S5, _S6O, _S6C),
        "npm_downloads": (_S9,),
        "pypistats": (_S9,),
    }
)
"""Static set of evidence keys each fact label contributes to (design §9.4).

Clients build ``Failure.feeds`` from this table; ``PackageFacts.absent`` uses the same
labels."""

NOTE_NO_REPO: Final = "no GitHub repo resolved"
NOTE_REPO_NOT_FOUND: Final = "repository not found"
NOTE_GITHUB_UNAVAILABLE: Final = "GitHub data unavailable"
NOTE_NOT_REPORTED: Final = "not reported by GitHub"
NOTE_NO_HISTORY: Final = "no default-branch history available"
NOTE_LOWER_BOUND: Final = "lower bound: commit history capped at the page limit"
NOTE_WINDOW: Final = "distinct commit authors in the 12 months to as_of"
NOTE_PUSHED: Final = "GitHub pushedAt of the repository"
NOTE_OPEN: Final = "all-time open issues"
NOTE_CLOSED: Final = "all-time closed issues"
NOTE_S1: Final = "npm: latest version deprecated OR repo archived; PyPI: repo archived only"
NOTE_S1_UNKNOWN: Final = "latest-version deprecation status unavailable"
NOTE_S1B: Final = "npm: resolved version deprecated AND latest version not deprecated"
NOTE_S1B_UNKNOWN: Final = "deprecation status of the resolved or latest version unavailable"
NOTE_PYPI_NO_DEPRECATION: Final = "PyPI exposes no deprecation signal"
NOTE_LATEST_FROM_DEPSDEV: Final = "latest version from deps.dev"
NOTE_LATEST_UNKNOWN: Final = "latest version unknown"
NOTE_S2_UNAVAILABLE: Final = "latest release date unavailable"
NOTE_NO_SCORECARD: Final = "no Scorecard available for this repo"
NOTE_NO_MAINTAINED: Final = "Scorecard has no Maintained check"
NOTE_NO_OVERALL: Final = "Scorecard has no overall score"
NOTE_SCORECARD_UNAVAILABLE: Final = "Scorecard data unavailable"
NOTE_OSV_UNAVAILABLE: Final = "OSV data unavailable"
NOTE_OSV_EMPTY: Final = "OSV lists no advisories for this version"
NOTE_OSV_LISTED: Final = "advisories listed by OSV"
NOTE_S9_UNKNOWN_PACKAGE: Final = "package unknown to the downloads source"
NOTE_S9_SKIPPED: Final = "not fetched: package cannot be Resting"
NOTE_S9_DEFERRED: Final = "not fetched yet: decided after the first pass"
NOTE_S9_UNAVAILABLE: Final = "downloads unavailable"
NOTE_OUT_OF_DOMAIN: Final = "value outside its domain was discarded"
NOTE_SOURCE_HAS_NO_RECORD: Final = " (source has no record)"

_DETAIL_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "OUT_OF_DOMAIN": "{source} returned a value outside its domain",
        "UNEXPECTED_SHAPE": "{source} returned an unexpected shape",
        "VERSION_NOT_FOUND": "resolved version not listed by {source}",
        "PAGINATION_TRUNCATED": "{source} history was truncated; the value is a lower bound",
        "GITHUB_DISABLED": "no GitHub token configured; GitHub signals unavailable",
        "INTERNAL_ERROR": "internal error while processing {source} data",
    }
)
_DETAIL_DEFAULT: Final = "{source} lookup failed: {code}"

type Origin = tuple[str, datetime]
type Latest = Literal["registry", "depsdev"]


# --- Kleene logic (D5) ----------------------------------------------------------------


def k_not(a: bool | None) -> bool | None:
    """Three-valued NOT: ``None`` stays ``None``."""
    return None if a is None else (not a)


def k_and(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued AND: ``False`` wins, then ``None``, else ``True``."""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def k_or(*parts: bool | None) -> bool | None:
    """Three-valued OR: ``True`` wins; ``False`` needs every part ``False``; else ``None``."""
    if any(p is True for p in parts):
        return True
    if any(p is None for p in parts):
        return None
    return False


# --- inputs ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sourced[T]:
    """A parsed fact with the URL it came from and when it was fetched from its origin.

    ``fetched_at`` must be timezone-aware UTC (SRC-API-4: a cache hit keeps the original
    time). ``extra_urls`` are further URLs that contributed (OSV advisory details).
    Violations raise ``ValueError``: that is a caller bug, not a source problem.
    """

    fact: T
    url: str
    fetched_at: datetime
    extra_urls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url:
            raise ValueError("Sourced.url must be a non-empty string")
        if self.fetched_at.utcoffset() != timedelta(0):
            raise ValueError("Sourced.fetched_at must be timezone-aware UTC")


@dataclass(frozen=True)
class PackageFacts:
    """Everything the per-package pipeline learned. ``None`` means "no usable answer".

    Only the registry of the package's own ecosystem is read (``registry_npm`` for npm,
    ``registry_pypi`` for PyPI). ``project`` is the deps.dev project document and
    ``scorecard`` the Scorecard API document (the fallback). ``github`` is the fact of the
    package's resolved repo. ``absent`` holds the ``FEEDS`` labels that answered 404
    (a definitive absence: a note, no warning, D4).
    """

    registry_npm: Sourced[NpmRegistry] | None = None
    registry_pypi: Sourced[PypiDoc] | None = None
    npm_full: Sourced[NpmFull] | None = None
    depsdev_resolved: Sourced[DepsDevVersion] | None = None
    depsdev_latest: Sourced[DepsDevVersion] | None = None
    depsdev_package: Sourced[DepsDevPackage] | None = None
    project: Sourced[DepsDevProject] | None = None
    scorecard: Sourced[DepsDevProject] | None = None
    osv: Sourced[tuple[OsvVuln, ...]] | None = None
    github: Sourced[GitHubRepo] | None = None
    absent: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Failure:
    """A source problem recorded during the pipeline (design §9.4).

    ``feeds`` is the static set of evidence keys the failing source contributes to (see
    ``FEEDS``). ``url`` is the URL that was attempted, used as the ``source_url`` of a
    missing signal. Validation errors raise ``ValueError`` (caller bug).
    """

    code: str
    source: str
    status: int | None
    feeds: tuple[str, ...]
    url: str | None = None

    def __post_init__(self) -> None:
        if self.code not in WARNING_CODES:
            raise ValueError(f"unknown warning code: {self.code!r}")
        if self.source not in SOURCE_NAMES:
            raise ValueError(f"unknown warning source: {self.source!r}")
        unknown = [key for key in self.feeds if key not in EVIDENCE_KEYS]
        if unknown:
            raise ValueError(f"unknown evidence keys in feeds: {sorted(unknown)!r}")
        if self.status is not None and (
            isinstance(self.status, bool) or not isinstance(self.status, int)
        ):
            raise ValueError("Failure.status must be an int or None")
        object.__setattr__(self, "feeds", tuple(sorted(set(self.feeds))))


@dataclass(frozen=True)
class RepoInfo:
    """The resolved repository (``repo_resolve.choose``): display form and how it was found."""

    repo: str | None = None
    via: RepoVia | None = None


@dataclass(frozen=True)
class Found:
    """Downloads were fetched. ``Downloads.weekly`` is ``None`` for an unknown package."""

    data: Sourced[Downloads]


@dataclass(frozen=True)
class Absent:
    """The downloads source answered 404 (definitive absence, no warning)."""

    url: str | None = None


@dataclass(frozen=True)
class Failed:
    """The downloads lookup failed; ``kind`` is a ``WARNING_CODES`` member."""

    kind: str
    status: int | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in WARNING_CODES:
            raise ValueError(f"unknown warning code: {self.kind!r}")


@dataclass(frozen=True)
class Skipped:
    """A PyPI package that cannot be Resting: pypistats was not asked (D14)."""


@dataclass(frozen=True)
class Deferred:
    """First pass for PyPI: S9 is decided after the first assembly (SRC-S9-3)."""


type DownloadsState = Found | Absent | Failed | Skipped | Deferred


# --- latest version -------------------------------------------------------------------


def resolve_latest(ecosystem: str, facts: PackageFacts) -> tuple[str | None, Latest | None]:
    """Return the latest version and where it came from (SRC-LAT-1).

    The registry of the package's ecosystem first; otherwise the deps.dev package
    document's ``isDefault`` version. ``(None, None)`` when neither is usable.
    """
    registry_latest: object = None
    if ecosystem == "npm":
        if facts.registry_npm is not None:
            registry_latest = facts.registry_npm.fact.latest
    elif facts.registry_pypi is not None:
        registry_latest = facts.registry_pypi.fact.latest
    if isinstance(registry_latest, str) and is_valid_version(registry_latest):
        return registry_latest, "registry"
    if facts.depsdev_package is not None:
        default: object = facts.depsdev_package.fact.default_version
        if isinstance(default, str) and is_valid_version(default):
            return default, "depsdev"
    return None, None


# --- domain guard ---------------------------------------------------------------------


class _Guard:
    """Checks values on their way in and records each rejection as a ``Failure``."""

    def __init__(self) -> None:
        self.problems: list[Failure] = []

    def _reject(self, keys: tuple[str, ...], source: str, *, numeric: bool) -> None:
        code = "OUT_OF_DOMAIN" if numeric else "UNEXPECTED_SHAPE"
        self.problems.append(Failure(code, source, None, keys))

    def flag(self, value: object, keys: tuple[str, ...], source: str) -> bool | None:
        out = as_bool(value)
        if out is None and value is not None:
            self._reject(keys, source, numeric=False)
        return out

    def count(self, value: object, keys: tuple[str, ...], source: str) -> int | None:
        out = as_int(value)
        if out is None and value is not None:
            numeric = isinstance(value, int) and not isinstance(value, bool)
            self._reject(keys, source, numeric=numeric)
        return out

    def score(self, value: object, keys: tuple[str, ...], source: str) -> float | None:
        out = as_score(value)
        if out is None and value is not None:
            numeric = isinstance(value, int | float) and not isinstance(value, bool)
            self._reject(keys, source, numeric=numeric)
        return out

    def day(self, value: object, keys: tuple[str, ...], source: str) -> date | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        self._reject(keys, source, numeric=False)
        return None


def _vuln_ok(vuln: object) -> bool:
    """True if ``vuln`` is an ``OsvVuln`` whose every field is in its domain (SRC-SEC-4)."""
    if not isinstance(vuln, OsvVuln):
        return False
    published: object = vuln.published_at
    return (
        isinstance(vuln.id, str)
        and is_valid_osv_id(vuln.id)
        and isinstance(vuln.withdrawn, bool)
        and isinstance(vuln.has_fix, bool)
        and (
            published is None
            or (isinstance(published, date) and not isinstance(published, datetime))
        )
        and isinstance(vuln.fixed_versions, tuple)
        and all(isinstance(v, str) and is_valid_version(v) for v in vuln.fixed_versions)
    )


def _vuln_key(vuln: OsvVuln) -> tuple[str, bool, date, tuple[str, ...]]:
    return (vuln.id, vuln.has_fix, vuln.published_at or date.min, vuln.fixed_versions)


# --- evidence helpers -----------------------------------------------------------------


def _origin(sourced: Sourced[object]) -> Origin:
    return (sourced.url, sourced.fetched_at)


def _present(
    value: JsonValue,
    origins: Sequence[Origin],
    note: str | None = None,
    extra_urls: Sequence[str] = (),
) -> Evidence:
    """Evidence for a known value; the first origin is primary, the rest are extras."""
    url, fetched_at = origins[0]
    extras = [u for u, _ in origins[1:]] + list(extra_urls)
    return Evidence(
        value=value,
        source_url=url,
        fetched_at=fetched_at,
        extra_source_urls=tuple(u for u in extras if u != url),
        note=note,
    )


def _missing(note: str, url: str | None = None) -> Evidence:
    return Evidence(value=None, source_url=url, fetched_at=None, note=note)


def _iso(day: date | None) -> JsonValue:
    return None if day is None else day.isoformat()


# --- construction of Signals with the re-validation pass (§9.3) -----------------------


@dataclass(frozen=True)
class _Values:
    s1: bool | None = None
    s1b: bool | None = None
    s2: date | None = None
    s3: date | None = None
    s4: float | None = None
    s5: int | None = None
    s6o: int | None = None
    s6c: int | None = None
    s7: tuple[Advisory, ...] | None = None
    s8: float | None = None
    s9: int | None = None


_COUNT_FIELDS: Final = (("s5", _S5), ("s6o", _S6O), ("s6c", _S6C), ("s9", _S9))
_SCORE_FIELDS: Final = (("s4", _S4), ("s8", _S8))


def _signals(purl: str, as_of: date, v: _Values) -> Signals:
    return Signals(
        purl=purl,
        as_of=as_of,
        s1_declared_death=v.s1,
        s1b_version_deprecated=v.s1b,
        s2_latest_release_at=v.s2,
        s3_last_push_at=v.s3,
        s4_maintained=v.s4,
        s5_committers=v.s5,
        s6_open_issues=v.s6o,
        s6_closed_issues=v.s6c,
        s7_advisories=v.s7,
        s8_overall=v.s8,
        s9_weekly_downloads=v.s9,
    )


def _revalidate(v: _Values) -> tuple[_Values, list[str]]:
    """Set every out-of-domain count and score to ``None``; return the keys that changed."""
    changed: list[str] = []
    fixed = v
    for attr, key in _COUNT_FIELDS:
        value: object = getattr(v, attr)
        if value is not None and as_int(value) is None:
            fixed = replace(fixed, **{attr: None})
            changed.append(key)
    for attr, key in _SCORE_FIELDS:
        value = getattr(v, attr)
        if value is not None and as_score(value) is None:
            fixed = replace(fixed, **{attr: None})
            changed.append(key)
    return fixed, changed


def _construct(purl: str, as_of: date, v: _Values) -> tuple[Signals, _Values, list[str]]:
    """Build ``Signals``; on ``ValueError`` blank the fields that break its domain (SRC-API-6).

    Returns the signals, the values actually used and the keys that were blanked. The guard
    in ``assemble`` makes the repair path unreachable from ``assemble``; the property test
    of SRC-TEST-5 checks that.
    """
    try:
        return _signals(purl, as_of, v), v, []
    except ValueError:
        pass
    repaired, changed = _revalidate(v)
    try:
        return _signals(purl, as_of, repaired), repaired, changed
    except ValueError:
        pass
    # Revalidation mirrors Signals.__post_init__, so this is a last resort: drop every
    # field that Signals validates and keep the unvalidated rest.
    blank = replace(repaired, s4=None, s8=None, s5=None, s6o=None, s6c=None, s9=None)
    return _signals(purl, as_of, blank), blank, [k for _, k in (*_COUNT_FIELDS, *_SCORE_FIELDS)]


# --- warnings -------------------------------------------------------------------------


def _detail(failure: Failure) -> str:
    template = _DETAIL_TEMPLATES.get(failure.code, _DETAIL_DEFAULT)
    text = template.format(source=failure.source, code=failure.code)
    if failure.status is not None:
        text += f" (status {failure.status})"
    return text


def _warning_key(w: SourceWarning) -> tuple[str, str, tuple[str, ...], str, int]:
    return (w.code, w.source, w.signals, w.detail, -1 if w.status is None else w.status)


# --- the assembler --------------------------------------------------------------------


def assemble(
    purl: Purl,
    as_of: date,
    facts: PackageFacts,
    failures: Sequence[Failure],
    repo_info: RepoInfo,
    downloads: DownloadsState,
) -> tuple[Signals, Mapping[str, Evidence], tuple[SourceWarning, ...]]:
    """Combine ``facts`` into ``(Signals, evidence, warnings)`` (design §9).

    ``evidence`` has exactly the 11 ``EVIDENCE_KEYS`` in order. ``failures`` are the
    problems the pipeline recorded; they become warnings whose ``signals`` are the
    ``feeds`` that ended up missing. ``Signals.purl`` is ``format_purl(purl)``.
    Never raises for the content of the facts (D3).
    """
    npm = purl.ecosystem == "npm"
    guard = _Guard()
    derived: list[Failure] = []
    ev: dict[str, Evidence] = {}

    def gap(key: str, base: str) -> str:
        hit = any(label in facts.absent and key in feeds for label, feeds in FEEDS.items())
        return base + NOTE_SOURCE_HAS_NO_RECORD if hit else base

    latest, latest_via = resolve_latest(purl.ecosystem, facts)
    from_depsdev = latest_via == "depsdev"

    # --- GitHub (S1 part, S3, S5, S6) ---
    github_gap = NOTE_NO_REPO
    gh: GitHubRepo | None = None
    gh_origin: Origin | None = None
    if repo_info.repo is not None:
        if facts.github is None:
            github_gap = NOTE_GITHUB_UNAVAILABLE
        elif facts.github.fact.found is not True:
            github_gap = NOTE_REPO_NOT_FOUND
        else:
            gh, gh_origin = facts.github.fact, _origin(facts.github)

    def github_count(
        key: str, raw: object, note: str, absent_note: str
    ) -> tuple[int | None, Evidence]:
        if gh_origin is None:
            return None, _missing(github_gap)
        value = guard.count(raw, (key,), "github")
        if value is None:
            return None, _missing(absent_note)
        return value, _present(value, [gh_origin], note)

    archived = guard.flag(gh.is_archived, (_S1,), "github") if gh is not None else None

    s3: date | None = None
    if gh_origin is None:
        ev[_S3] = _missing(github_gap)
    else:
        s3 = guard.day(gh.pushed_at if gh is not None else None, (_S3,), "github")
        ev[_S3] = (
            _present(s3.isoformat(), [gh_origin], NOTE_PUSHED)
            if s3 is not None
            else _missing(NOTE_NOT_REPORTED)
        )
    s6o, ev[_S6O] = github_count(
        _S6O, gh.open_issues if gh is not None else None, NOTE_OPEN, NOTE_NOT_REPORTED
    )
    s6c, ev[_S6C] = github_count(
        _S6C, gh.closed_issues if gh is not None else None, NOTE_CLOSED, NOTE_NOT_REPORTED
    )
    lower_bound = gh is not None and gh.committers_lower_bound is True
    s5, ev[_S5] = github_count(
        _S5,
        gh.committers if gh is not None else None,
        NOTE_LOWER_BOUND if lower_bound else NOTE_WINDOW,
        NOTE_NO_HISTORY,
    )
    if s5 is not None and lower_bound:
        derived.append(Failure("PAGINATION_TRUNCATED", "github", None, (_S5,)))

    # --- S1 and S1b ---
    registry_found_false = False
    lat_dep: bool | None = None
    res_dep: bool | None = None
    lat_origin: Origin | None = None
    res_origin: Origin | None = None
    if npm:
        reg_npm = facts.registry_npm
        registry_found_false = reg_npm is not None and reg_npm.fact.resolved_found is False
        reg_usable = reg_npm if not registry_found_false else None

        def deprecated(
            doc: Sourced[DepsDevVersion] | None, latest_flag: bool
        ) -> tuple[bool | None, Origin | None]:
            keys = (_S1, _S1B) if latest_flag else (_S1B,)
            if doc is not None:
                found = guard.flag(doc.fact.is_deprecated, keys, "depsdev")
                if found is not None:
                    return found, _origin(doc)
            if reg_usable is not None:
                raw = (
                    reg_usable.fact.latest_deprecated
                    if latest_flag
                    else reg_usable.fact.resolved_deprecated
                )
                found = guard.flag(raw, keys, "npm_registry")
                if found is not None:
                    return found, _origin(reg_usable)
            return None, None

        lat_dep, lat_origin = deprecated(facts.depsdev_latest, True)
        res_dep, res_origin = deprecated(facts.depsdev_resolved, False)
        if registry_found_false:
            derived.append(Failure("VERSION_NOT_FOUND", "npm_registry", None, (_S1, _S1B)))
    elif facts.registry_pypi is not None and facts.registry_pypi.fact.resolved_found is False:
        registry_found_false = True
        derived.append(Failure("VERSION_NOT_FOUND", "pypi", None, ()))

    s1 = k_or(lat_dep, archived) if npm else k_or(archived)
    s1_origins = [
        o
        for o in (
            lat_origin if lat_dep is not None else None,
            gh_origin if archived is not None else None,
        )
        if o
    ]
    if s1 is not None and s1_origins:
        use_depsdev_note = npm and from_depsdev and lat_dep is not None
        ev[_S1] = _present(
            s1, s1_origins, NOTE_LATEST_FROM_DEPSDEV if use_depsdev_note else NOTE_S1
        )
    else:
        if archived is None:
            why = github_gap if gh is None else NOTE_NOT_REPORTED
        else:
            why = gap(_S1, NOTE_S1_UNKNOWN)
        ev[_S1] = _missing(why)

    if npm:
        s1b = k_and(res_dep, k_not(lat_dep))
        s1b_origins = [
            o
            for o in (
                res_origin if res_dep is not None else None,
                lat_origin if lat_dep is not None else None,
            )
            if o
        ]
        if s1b is not None and s1b_origins:
            use_depsdev_note = from_depsdev and lat_dep is not None
            ev[_S1B] = _present(
                s1b, s1b_origins, NOTE_LATEST_FROM_DEPSDEV if use_depsdev_note else NOTE_S1B
            )
        else:
            ev[_S1B] = _missing(gap(_S1B, NOTE_S1B_UNKNOWN))
    else:
        s1b = None
        ev[_S1B] = _missing(
            NOTE_PYPI_NO_DEPRECATION,
            facts.registry_pypi.url if facts.registry_pypi is not None else None,
        )

    # --- S2 ---
    s2: date | None = None
    s2_options: list[tuple[object, str, Origin]] = []
    if facts.depsdev_latest is not None:
        s2_options.append(
            (facts.depsdev_latest.fact.published_at, "depsdev", _origin(facts.depsdev_latest))
        )
    if npm and facts.npm_full is not None:
        s2_options.append(
            (facts.npm_full.fact.latest_published, "npm_registry", _origin(facts.npm_full))
        )
    if not npm and facts.registry_pypi is not None:
        s2_options.append(
            (facts.registry_pypi.fact.latest_published, "pypi", _origin(facts.registry_pypi))
        )
    for raw_date, source, origin in s2_options:
        s2 = guard.day(raw_date, (_S2,), source)
        if s2 is not None:
            ev[_S2] = _present(
                s2.isoformat(), [origin], NOTE_LATEST_FROM_DEPSDEV if from_depsdev else None
            )
            break
    if s2 is None:
        ev[_S2] = _missing(NOTE_LATEST_UNKNOWN if latest is None else gap(_S2, NOTE_S2_UNAVAILABLE))

    # --- S4 and S8: one document ---
    s4: float | None = None
    s8: float | None = None
    card_origin: Origin | None = None
    card_documents: list[tuple[Sourced[DepsDevProject], str]] = []
    if facts.project is not None:
        card_documents.append((facts.project, "depsdev"))
    if facts.scorecard is not None:
        card_documents.append((facts.scorecard, "scorecard"))
    if repo_info.repo is not None:
        for doc, source in card_documents:
            maintained = guard.score(doc.fact.maintained, (_S4,), source)
            overall = guard.score(doc.fact.overall, (_S8,), source)
            if maintained is not None or overall is not None:
                s4, s8, card_origin = maintained, overall, _origin(doc)
                break
    if repo_info.repo is None:
        card_gap4 = card_gap8 = NOTE_NO_REPO
    elif card_origin is not None:
        card_gap4, card_gap8 = NOTE_NO_MAINTAINED, NOTE_NO_OVERALL
    elif card_documents:
        card_gap4 = card_gap8 = NOTE_NO_SCORECARD
    else:
        card_gap4 = gap(_S4, NOTE_SCORECARD_UNAVAILABLE)
        card_gap8 = gap(_S8, NOTE_SCORECARD_UNAVAILABLE)
    ev[_S4] = _present(s4, [card_origin]) if s4 is not None and card_origin else _missing(card_gap4)
    ev[_S8] = _present(s8, [card_origin]) if s8 is not None and card_origin else _missing(card_gap8)

    # --- S7 ---
    s7: tuple[Advisory, ...] | None = None
    if facts.osv is None:
        ev[_S7] = _missing(gap(_S7, NOTE_OSV_UNAVAILABLE))
    else:
        vulns: object = facts.osv.fact
        if not isinstance(vulns, tuple) or not all(_vuln_ok(v) for v in vulns):
            guard.problems.append(Failure("UNEXPECTED_SHAPE", "osv", None, (_S7,)))
            ev[_S7] = _missing(NOTE_OSV_UNAVAILABLE, facts.osv.url)
        else:
            live = sorted((v for v in vulns if not v.withdrawn), key=_vuln_key)
            s7 = tuple(Advisory(v.id, v.has_fix, v.published_at) for v in live)
            listed: JsonValue = [
                {
                    "id": v.id,
                    "has_fix": v.has_fix,
                    "published_at": _iso(v.published_at),
                    "fixed_versions": list(v.fixed_versions),
                }
                for v in live
            ]
            ev[_S7] = _present(
                listed,
                [_origin(facts.osv)],
                NOTE_OSV_LISTED if live else NOTE_OSV_EMPTY,
                facts.osv.extra_urls,
            )

    # --- S9 ---
    s9: int | None = None
    dl_source = "npm_downloads" if npm else "pypistats"
    match downloads:
        case Found(data=data):
            weekly = guard.count(data.fact.weekly, (_S9,), dl_source)
            if weekly is not None:
                s9 = weekly
                ev[_S9] = _present(weekly, [_origin(data)])
            else:
                ev[_S9] = _missing(NOTE_S9_UNKNOWN_PACKAGE, data.url)
        case Absent(url=url):
            ev[_S9] = _missing(NOTE_S9_UNKNOWN_PACKAGE, url)
        case Failed(kind=kind, status=status, url=url):
            derived.append(Failure(kind, dl_source, status, (_S9,), url))
            ev[_S9] = _missing(NOTE_S9_UNAVAILABLE, url)
        case Skipped():
            ev[_S9] = _missing(NOTE_S9_SKIPPED)
        case Deferred():
            ev[_S9] = _missing(NOTE_S9_DEFERRED)

    # --- Signals, with the re-validation pass ---
    values = _Values(
        s1=s1, s1b=s1b, s2=s2, s3=s3, s4=s4, s5=s5, s6o=s6o, s6c=s6c, s7=s7, s8=s8, s9=s9
    )
    signals, _used, repaired = _construct(format_purl(purl), as_of, values)
    for key in repaired:
        ev[key] = _missing(NOTE_OUT_OF_DOMAIN)
        guard.problems.append(Failure("OUT_OF_DOMAIN", "internal", None, (key,)))

    # --- warnings ---
    problems = [*failures, *guard.problems, *derived]
    missing_keys = {key for key, e in ev.items() if e.value is None}
    for key in missing_keys:
        if ev[key].source_url is None:
            urls = sorted({f.url for f in problems if f.url is not None and key in f.feeds})
            if urls:
                ev[key] = replace(ev[key], source_url=urls[0])
    warnings = {
        SourceWarning(
            code=f.code,
            source=f.source,
            signals=tuple(sorted(set(f.feeds) & missing_keys)),
            detail=_detail(f),
            status=f.status,
        )
        for f in problems
    }
    evidence = MappingProxyType({key: ev[key] for key in EVIDENCE_KEYS})
    return signals, evidence, tuple(sorted(warnings, key=_warning_key))
