"""Shared Hypothesis strategies for the ``core.sources`` tests.

* ``json_like()`` produces arbitrary parsed-JSON-like input, plus objects a JSON
  parser never yields (bytes, tuples, frozensets, dates, ``object()``), so the
  total-function properties (SRC-TEST-4) cover hostile shapes. Size is bounded.
* ``shaped_json()`` / ``parser_input()`` build documents from the keys the parsers read.
* ``all_facts()`` and one strategy per fact class produce in-domain facts.
* ``token_shapes()`` produces GitHub-token-shaped strings. They are assembled at run
  time from generated characters, so no token-shaped literal sits in source and
  gitleaks stays quiet.

* ``osv_vuln_docs()`` produces OSV vulnerability documents for the ``has_fix`` property
  (SRC-TEST-3), with ``QUERY_ECOSYSTEM`` / ``QUERY_NAME`` as the queried package.
* ``package_scenarios()`` produces everything ``assemble`` takes (SRC-TEST-5, T6.4), with
  facts built directly so that wrong types, out-of-domain numbers, ``bool`` where an ``int``
  is wanted, ``NaN`` and malformed advisories are common. ``scoring_signals()`` and
  ``weights_variants()`` feed the Resting-candidate property (SRC-TEST-15).
"""

from __future__ import annotations

import copy
import string
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from hypothesis import strategies as st

from core.purl import Purl, parse_purl
from core.scoring.types import Advisory, Signals, Weights
from core.scoring.weights import load_weights
from core.sources.assemble import (
    FEEDS,
    Absent,
    Deferred,
    DownloadsState,
    Failed,
    Failure,
    Found,
    PackageFacts,
    RepoInfo,
    Skipped,
    Sourced,
)
from core.sources.facts import (
    DepsDevPackage,
    DepsDevProject,
    DepsDevVersion,
    Downloads,
    GitHubRepo,
    NpmFull,
    NpmRegistry,
    OsvIds,
    OsvVuln,
    PypiDoc,
)
from core.sources.model import EVIDENCE_KEYS, SOURCE_NAMES, WARNING_CODES
from core.sources.repo_resolve import RESERVED_OWNERS
from core.sources.urls import strip_userinfo

_ALNUM = string.ascii_letters + string.digits
_CLASSIC_KINDS = "pousr"

_DATE_STRINGS = (
    "",
    " ",
    "2026-11-03",
    "2026-11-03T10:00:00",
    "2026-11-03T10:00:00Z",
    "2026-11-03T23:30:00-05:00",
    "2026-11-03T00:30:00+05:30",
    "0000-00-00",
    "9999-12-31T23:59:59-23:59",
    "not a date",
    "2" * 200,
)


def _offset_datetimes() -> st.SearchStrategy[datetime]:
    zones = st.builds(
        lambda minutes: timezone(timedelta(minutes=minutes)), st.integers(-1439, 1439)
    )
    return st.datetimes(timezones=st.one_of(st.just(UTC), zones))


def _leaves() -> st.SearchStrategy[object]:
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.integers(min_value=10**30, max_value=10**60),
        st.just(10**400),
        st.just(-(10**400)),
        st.floats(allow_nan=True, allow_infinity=True),
        st.text(max_size=40),
        st.sampled_from(_DATE_STRINGS),
        _offset_datetimes().map(lambda moment: moment.isoformat()),
        st.binary(max_size=10),
        st.dates(),
        _offset_datetimes(),
        st.frozensets(st.integers(), max_size=3),
        st.builds(object),
    )


def _extend(children: st.SearchStrategy[object]) -> st.SearchStrategy[object]:
    return st.one_of(
        st.lists(children, max_size=4),
        st.tuples(children, children),
        st.dictionaries(st.text(max_size=8), children, max_size=4),
        st.dictionaries(st.integers(), children, max_size=3),
    )


def json_like(max_leaves: int = 20) -> st.SearchStrategy[object]:
    """Arbitrary JSON-like input, including NaN, infinities, huge ints and non-JSON objects."""
    return st.recursive(_leaves(), _extend, max_leaves=max_leaves)


_VOCABULARY = (
    # deps.dev
    "relatedProjects", "relationType", "SOURCE_REPO", "projectKey", "id", "links",
    "label", "url", "isDeprecated", "publishedAt", "versions", "isDefault",
    "versionKey", "version", "scorecard", "overallScore", "checks", "name",
    "Maintained", "score",
    # registries
    "dist-tags", "latest", "deprecated", "time", "repository", "info", "urls",
    "releases", "upload_time_iso_8601", "project_urls", "home_page", "download_url",
    # downloads
    "downloads", "data", "last_week",
)  # fmt: skip
"""Keys and values the parsers look for, so generated documents reach deep branches."""

_VOCABULARY_VALUES = (
    "SOURCE_REPO",
    "Maintained",
    "1.0.0",
    "2026-11-03",
    "2026-11-03T10:00:00Z",
    "https://github.com/o/r",
    "git+https://github.com/o/r.git",
)


def _shaped_leaves() -> st.SearchStrategy[object]:
    return st.one_of(
        _leaves(),
        st.sampled_from(_VOCABULARY_VALUES),
        st.integers(-1, 12),
        st.floats(-1, 11),
        st.booleans(),
    )


def _shaped_extend(children: st.SearchStrategy[object]) -> st.SearchStrategy[object]:
    keys = st.one_of(st.sampled_from(_VOCABULARY), st.text(max_size=6))
    return st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(keys, children, max_size=5),
        st.dictionaries(keys, children, max_size=5),
    )


def shaped_json(max_leaves: int = 25) -> st.SearchStrategy[object]:
    """Documents built from the keys and values the source parsers read.

    ``json_like()`` almost never hits a key such as ``dist-tags``; this strategy does, with
    wrong types and bad values below it, so the parsers' inner branches run.
    """
    return st.recursive(_shaped_leaves(), _shaped_extend, max_leaves=max_leaves)


def _maybe(strategy: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """Mostly ``strategy``, sometimes arbitrary JSON-like junk in its place."""
    return st.one_of(*([strategy] * 7), json_like(max_leaves=4))


@st.composite
def _opt_dict(
    draw: st.DrawFn,
    required: dict[str, st.SearchStrategy[Any]],
    optional: dict[str, st.SearchStrategy[Any]],
) -> dict[str, Any]:
    """A mapping with every required key and most optional keys, each value maybe corrupted."""
    out: dict[str, Any] = {key: draw(_maybe(value)) for key, value in required.items()}
    for key, value in optional.items():
        if draw(st.integers(0, 5)) > 0:
            out[key] = draw(_maybe(value))
    return out


_TIMESTAMPS = st.one_of(
    st.sampled_from(_DATE_STRINGS), _offset_datetimes().map(lambda moment: moment.isoformat())
)
_URLS = st.one_of(
    st.sampled_from(
        (
            "https://github.com/o/r",
            "git+https://github.com/o/r.git",
            "git@github.com:o/r.git",
            "https://example.org/x",
            "",
        )
    ),
    st.text(max_size=20),
)
_SCORES = st.one_of(
    st.integers(-2, 11),
    st.floats(-2, 11),
    st.just(True),
    st.just(float("nan")),
    st.text(max_size=3),
)
_VERSIONS = st.one_of(
    st.sampled_from(("1.0.0", "2.3.4", "0.0.1", "1.0+local")), st.text(max_size=6)
)


def depsdev_version_docs() -> st.SearchStrategy[dict[str, Any]]:
    related = st.fixed_dictionaries(
        {
            "relationType": st.sampled_from(("SOURCE_REPO", "ISSUE_TRACKER", "")),
            "projectKey": _maybe(_opt_dict({"id": _URLS}, {})),
        }
    )
    links = st.fixed_dictionaries(
        {"label": st.sampled_from(("SOURCE_REPO", "HOMEPAGE")), "url": _URLS}
    )
    return _opt_dict(
        {},
        {
            "isDeprecated": st.booleans(),
            "publishedAt": _TIMESTAMPS,
            "relatedProjects": st.lists(_maybe(related), max_size=3),
            "links": st.lists(_maybe(links), max_size=3),
        },
    )


def depsdev_package_docs() -> st.SearchStrategy[dict[str, Any]]:
    entry = _opt_dict(
        {}, {"isDefault": st.booleans(), "versionKey": _opt_dict({}, {"version": _VERSIONS})}
    )
    return _opt_dict({"versions": st.lists(entry, max_size=4)}, {})


def _checks() -> st.SearchStrategy[list[Any]]:
    check = _opt_dict({}, {"name": st.sampled_from(("Maintained", "Other")), "score": _SCORES})
    return st.lists(check, max_size=3)


def depsdev_project_docs() -> st.SearchStrategy[dict[str, Any]]:
    card = _opt_dict({}, {"overallScore": _SCORES, "checks": _checks()})
    return _opt_dict({}, {"scorecard": card})


def scorecard_api_docs() -> st.SearchStrategy[dict[str, Any]]:
    return _opt_dict({}, {"score": _SCORES, "checks": _checks()})


def npm_abbreviated_docs() -> st.SearchStrategy[dict[str, Any]]:
    entry = _opt_dict({}, {"deprecated": st.one_of(st.text(max_size=5), st.booleans(), st.none())})
    return _opt_dict(
        {},
        {
            "dist-tags": _opt_dict({}, {"latest": _VERSIONS}),
            "versions": st.dictionaries(_VERSIONS, entry, max_size=3),
        },
    )


def npm_full_docs() -> st.SearchStrategy[dict[str, Any]]:
    return _opt_dict(
        {},
        {
            "time": st.dictionaries(_VERSIONS, _TIMESTAMPS, max_size=3),
            "repository": st.one_of(_URLS, _opt_dict({}, {"url": _URLS})),
        },
    )


def pypi_json_docs() -> st.SearchStrategy[dict[str, Any]]:
    upload = _opt_dict({}, {"upload_time_iso_8601": _TIMESTAMPS})
    files = st.lists(upload, max_size=3)
    info = _opt_dict(
        {},
        {
            "version": _VERSIONS,
            "project_urls": st.dictionaries(st.text(max_size=8), _URLS, max_size=4),
            "home_page": _URLS,
            "download_url": _URLS,
        },
    )
    return _opt_dict(
        {}, {"info": info, "urls": files, "releases": st.dictionaries(_VERSIONS, files, max_size=3)}
    )


def downloads_docs() -> st.SearchStrategy[dict[str, Any]]:
    count = st.one_of(st.integers(-2, 10**9), st.just(True), st.floats(), st.text(max_size=3))
    return _opt_dict(
        {},
        {
            "downloads": count,
            "package": st.text(max_size=5),
            "data": _opt_dict({}, {"last_week": count}),
        },
    )


def document_shaped() -> st.SearchStrategy[Any]:
    """Documents in the shapes of design §6, with fields randomly corrupted or missing."""
    return st.one_of(
        depsdev_version_docs(),
        depsdev_package_docs(),
        depsdev_project_docs(),
        scorecard_api_docs(),
        npm_abbreviated_docs(),
        npm_full_docs(),
        pypi_json_docs(),
        downloads_docs(),
    )


def parser_input() -> st.SearchStrategy[object]:
    """Arbitrary JSON-like input, vocabulary-shaped input, or a corrupted real-shaped document."""
    return st.one_of(
        json_like(), shaped_json(), document_shaped(), document_shaped(), document_shaped()
    )


# --- facts (in-domain values only) --------------------------------------------------------

_VERSION_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._+!~-]{0,99}"
_OSV_ID_PATTERN = r"[A-Za-z0-9_.:-]{1,100}"


def version_strings() -> st.SearchStrategy[str]:
    """Strings accepted by ``is_valid_version``."""
    return st.from_regex(_VERSION_PATTERN, fullmatch=True)


def osv_ids() -> st.SearchStrategy[str]:
    """Strings accepted by ``is_valid_osv_id``."""
    return st.from_regex(_OSV_ID_PATTERN, fullmatch=True)


def fact_dates() -> st.SearchStrategy[date]:
    return st.dates()


def fact_scores() -> st.SearchStrategy[float]:
    """A score in [0, 10] or exactly -1 (as ``float``)."""
    return st.one_of(st.floats(0, 10), st.just(-1.0))


def fact_counts() -> st.SearchStrategy[int]:
    return st.one_of(st.integers(0, 10**6), st.integers(0, 10**30))


def _optional(strategy: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return st.one_of(st.none(), strategy)


def _candidates() -> st.SearchStrategy[tuple[str, ...]]:
    return st.lists(st.text(max_size=60), max_size=4).map(tuple)


def depsdev_versions() -> st.SearchStrategy[DepsDevVersion]:
    return st.builds(
        DepsDevVersion,
        is_deprecated=_optional(st.booleans()),
        published_at=_optional(fact_dates()),
        repo_candidates=_candidates(),
    )


def depsdev_packages() -> st.SearchStrategy[DepsDevPackage]:
    return st.builds(DepsDevPackage, default_version=_optional(version_strings()))


def depsdev_projects() -> st.SearchStrategy[DepsDevProject]:
    return st.builds(
        DepsDevProject,
        maintained=_optional(fact_scores()),
        overall=_optional(fact_scores()),
        has_scorecard=st.booleans(),
    )


def npm_registries() -> st.SearchStrategy[NpmRegistry]:
    return st.builds(
        NpmRegistry,
        latest=_optional(version_strings()),
        latest_deprecated=_optional(st.booleans()),
        resolved_deprecated=_optional(st.booleans()),
        resolved_found=st.booleans(),
    )


def npm_fulls() -> st.SearchStrategy[NpmFull]:
    return st.builds(
        NpmFull, latest_published=_optional(fact_dates()), repo_candidates=_candidates()
    )


def pypi_docs() -> st.SearchStrategy[PypiDoc]:
    return st.builds(
        PypiDoc,
        latest=_optional(version_strings()),
        latest_published=_optional(fact_dates()),
        resolved_found=_optional(st.booleans()),
        repo_candidates=_candidates(),
    )


def downloads() -> st.SearchStrategy[Downloads]:
    return st.builds(Downloads, weekly=_optional(fact_counts()))


def osv_id_facts() -> st.SearchStrategy[OsvIds]:
    return st.builds(OsvIds, ids=st.lists(osv_ids(), max_size=5).map(tuple))


@st.composite
def osv_vulns(draw: st.DrawFn) -> OsvVuln:
    """An ``OsvVuln`` with sorted, unique ``fixed_versions`` and a consistent ``has_fix``."""
    fixed = tuple(sorted(set(draw(st.lists(version_strings(), max_size=4)))))
    return OsvVuln(
        id=draw(osv_ids()),
        withdrawn=draw(st.booleans()),
        published_at=draw(_optional(fact_dates())),
        fixed_versions=fixed,
        has_fix=bool(fixed),
    )


@st.composite
def github_repos(draw: st.DrawFn) -> GitHubRepo:
    """A ``GitHubRepo`` obeying the consistency rules of ``facts.py``."""
    if not draw(st.booleans()):
        return GitHubRepo(
            is_archived=None,
            pushed_at=None,
            open_issues=None,
            closed_issues=None,
            committers=None,
            committers_lower_bound=False,
            found=False,
        )
    committers = draw(_optional(fact_counts()))
    return GitHubRepo(
        is_archived=draw(_optional(st.booleans())),
        pushed_at=draw(_optional(fact_dates())),
        open_issues=draw(_optional(fact_counts())),
        closed_issues=draw(_optional(fact_counts())),
        committers=committers,
        committers_lower_bound=committers is not None and draw(st.booleans()),
        found=True,
    )


def all_facts() -> st.SearchStrategy[Any]:
    """An in-domain instance of any of the ten fact classes."""
    return st.one_of(
        depsdev_versions(),
        depsdev_packages(),
        depsdev_projects(),
        npm_registries(),
        npm_fulls(),
        pypi_docs(),
        downloads(),
        osv_id_facts(),
        osv_vulns(),
        github_repos(),
    )


FACT_CLASSES: tuple[type, ...] = (
    DepsDevVersion,
    DepsDevPackage,
    DepsDevProject,
    NpmRegistry,
    NpmFull,
    PypiDoc,
    Downloads,
    OsvIds,
    OsvVuln,
    GitHubRepo,
)


def classic_tokens() -> st.SearchStrategy[str]:
    """``gh[pousr]_`` followed by 20 or more alphanumerics."""
    return st.builds(
        lambda kind, body: "gh" + kind + "_" + body,
        st.sampled_from(_CLASSIC_KINDS),
        st.text(_ALNUM, min_size=20, max_size=60),
    )


def fine_grained_tokens() -> st.SearchStrategy[str]:
    """The fine-grained shape: ``github`` + ``_pat_`` + 20 or more of ``[A-Za-z0-9_]``."""
    return st.builds(
        lambda body: "github" + "_pat_" + body,
        st.text(_ALNUM + "_", min_size=20, max_size=60),
    )


def token_shapes() -> st.SearchStrategy[str]:
    """Either token shape."""
    return st.one_of(classic_tokens(), fine_grained_tokens())


def noise() -> st.SearchStrategy[str]:
    """Text to put around a token: includes characters that continue a token run."""
    return st.one_of(
        st.text(_ALNUM + "_[]", max_size=12),
        st.text(max_size=12),
    )


@st.composite
def embedded_token(draw: st.DrawFn) -> str:
    """A string with at least one token-shaped substring and arbitrary text around it."""
    parts = [draw(noise()), draw(token_shapes()), draw(noise())]
    if draw(st.booleans()):
        parts.extend([draw(token_shapes()), draw(noise())])
    return "".join(parts)


# --- OSV vulnerability documents (SRC-TEST-3) ---------------------------------------------

QUERY_ECOSYSTEM = "PyPI"
QUERY_NAME = "flask-sqlalchemy"
"""The package ``osv_vuln_docs()`` is written for. Pass these to ``has_fix``."""


def query_package() -> dict[str, str]:
    """A fresh ``affected[].package`` object that matches ``QUERY_ECOSYSTEM``/``QUERY_NAME``."""
    return {"ecosystem": QUERY_ECOSYSTEM, "name": QUERY_NAME}


@st.composite
def _weighted(draw: st.DrawFn, *options: tuple[st.SearchStrategy[Any], int]) -> Any:
    """Draw from one of the strategies, chosen with integer weights.

    Repeating a strategy inside ``st.one_of`` would give a repr that grows exponentially with
    nesting, so the choice is made by an integer draw instead (it shrinks to the first option).
    """
    pick = draw(st.integers(0, sum(weight for _, weight in options) - 1))
    for strategy, weight in options:
        if pick < weight:
            return draw(strategy)
        pick -= weight
    raise AssertionError("unreachable")  # pragma: no cover


_JSON_JUNK: st.SearchStrategy[Any] = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(),
    st.text(max_size=6),
    st.lists(st.text(max_size=3), max_size=2),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
)
"""A value of the wrong type for almost every slot of an OSV document."""


@st.composite
def _sparse(
    draw: st.DrawFn, fields: dict[str, tuple[st.SearchStrategy[Any], int]]
) -> dict[str, Any]:
    """A mapping where each field is present with probability ``keep / 10``."""
    out: dict[str, Any] = {}
    for key, (strategy, keep) in fields.items():
        if draw(st.integers(1, 10)) <= keep:
            out[key] = draw(strategy)
    return out


_NAME_CASES: dict[str, Callable[[str], str]] = {
    "lower": str.lower,
    "upper": str.upper,
    "title": str.title,
    "swapcase": str.swapcase,
}


def _spelling(sep: str, left: str, right: str) -> str:
    return _NAME_CASES[left]("flask") + sep + _NAME_CASES[right]("sqlalchemy")


_SEPARATORS = st.sampled_from(("-", "_", ".", "--", "_.", "-_-", ".."))
_SPELLINGS = st.one_of(
    st.sampled_from(
        (
            "flask-sqlalchemy",
            "Flask_SQLAlchemy",
            "flask-sqlalchemy",
            "FLASK.SQLAlchemy",
            "Flask-SQLAlchemy",
            "flask__sqlalchemy",
            "FLASK_-.SQLALCHEMY",
        )
    ),
    st.builds(
        _spelling,
        _SEPARATORS,
        st.sampled_from(sorted(_NAME_CASES)),
        st.sampled_from(sorted(_NAME_CASES)),
    ),
)
"""Spellings of ``QUERY_NAME`` that are equal after PEP 503 normalisation."""

_NEAR_MISSES = st.sampled_from(
    (
        "flask-sqlalchemy2",
        "flask_sql_alchemy",
        "flasksqlalchemy",
        "sqlalchemy",
        "flask",
        "Flask-SQLAlchemy-Utils",
        "flask sqlalchemy",
        " flask-sqlalchemy",
        "flask-sqlalchemy ",
        "flask-sqlalchemy\n",
        "",
        "express",
    )
)
_OTHER_ECOSYSTEMS = st.sampled_from(("npm", "pypi", "PYPI", "PyPI ", "Go", "Maven", ""))


def _packages() -> st.SearchStrategy[Any]:
    """``affected[].package`` values: matching, partly matching, or wrongly typed."""
    name = _weighted((_SPELLINGS, 6), (_NEAR_MISSES, 3), (_JSON_JUNK, 1))
    ecosystem = _weighted((st.just(QUERY_ECOSYSTEM), 7), (_OTHER_ECOSYSTEMS, 3), (_JSON_JUNK, 1))
    matching = st.fixed_dictionaries({"ecosystem": st.just(QUERY_ECOSYSTEM), "name": _SPELLINGS})
    general = _weighted(
        (st.fixed_dictionaries({"name": name, "ecosystem": ecosystem}), 3),
        (
            _sparse(
                {
                    "name": (name, 6),
                    "ecosystem": (ecosystem, 6),
                    "purl": (st.text(max_size=20), 5),
                }
            ),
            2,
        ),
    )
    return _weighted((matching, 7), (general, 3), (_JSON_JUNK, 1))


_VALID_VERSIONS = st.one_of(
    st.sampled_from(("1.0.0", "2.3.4rc1", "1!2.0", "0.9+local", "1.0~beta", "v1", "A", "a" * 100)),
    version_strings(),
    st.text("0123456789abcdef", min_size=40, max_size=40),
)
_INVALID_STRINGS = st.one_of(
    st.sampled_from(
        (
            "",
            " ",
            "1.0 ",
            " 1.0",
            "-1.0",
            "_1",
            "1.0\n",
            "1.0\u00e9",
            "1/2",
            "1;2",
            "1 0",
            "1.0\x00",
            "\u0663.\u0660",
            "a" * 101,
            "x" * 5000,
        )
    ),
    st.text(max_size=8),
)
_NON_STRINGS = st.sampled_from(
    (None, 0, 1, 1.5, True, False, [], ["1.0"], {}, {"v": "1.0"}, {"fixed": "1.0"})
).map(copy.deepcopy)
_FIXED_VALUES = _weighted((_VALID_VERSIONS, 8), (_INVALID_STRINGS, 3), (_NON_STRINGS, 2))


def _events() -> st.SearchStrategy[Any]:
    """One entry of ``ranges[].events``: a single-key event, a mixed one, or junk."""
    introduced = _weighted((st.just("0"), 1), (version_strings(), 1))
    last_affected = version_strings()
    limit = _weighted((st.just("*"), 1), (version_strings(), 1))
    return _weighted(
        (st.fixed_dictionaries({"introduced": introduced}), 3),
        (st.fixed_dictionaries({"fixed": _FIXED_VALUES}), 6),
        (st.fixed_dictionaries({"last_affected": last_affected}), 2),
        (st.fixed_dictionaries({"limit": limit}), 2),
        (
            _sparse(
                {
                    "introduced": (introduced, 5),
                    "fixed": (_FIXED_VALUES, 5),
                    "last_affected": (last_affected, 3),
                    "limit": (limit, 3),
                }
            ),
            2,
        ),
        (st.builds(dict), 1),
        (_JSON_JUNK, 1),
    )


def _ranges() -> st.SearchStrategy[Any]:
    """``affected[].ranges``: a list of ranges with the three real types and odd ones."""
    range_type = _weighted(
        (st.sampled_from(("SEMVER", "ECOSYSTEM")), 5),
        (st.just("GIT"), 3),
        (st.sampled_from(("git", "Git", "GIT ", "", None, 5, ["GIT"])), 1),
    )
    events = _weighted(
        (st.lists(_events(), min_size=1, max_size=5), 7), (st.builds(list), 1), (_JSON_JUNK, 1)
    )
    one_range = _sparse(
        {"type": (range_type, 9), "events": (events, 9), "repo": (st.text(max_size=20), 3)}
    )
    return _weighted(
        (st.lists(_weighted((one_range, 8), (_JSON_JUNK, 1)), min_size=1, max_size=3), 8),
        (st.builds(list), 1),
        (_JSON_JUNK, 1),
    )


def _decoy_fix() -> dict[str, Any]:
    """A fix in the shape of an ``affected`` entry, put where ``has_fix`` must not look."""
    return {"ranges": [{"type": "SEMVER", "events": [{"fixed": "9.9.9"}]}]}


def _affected_entries() -> st.SearchStrategy[Any]:
    entry = _sparse(
        {
            "package": (_packages(), 9),
            "ranges": (_ranges(), 9),
            "versions": (st.lists(version_strings(), max_size=3), 3),
            "ecosystem_specific": (st.builds(_decoy_fix), 2),
            "database_specific": (st.builds(_decoy_fix), 2),
        }
    )
    slot = _weighted((entry, 9), (_JSON_JUNK, 1))
    return _weighted(
        (st.lists(slot, min_size=1, max_size=4), 8), (st.builds(list), 1), (_JSON_JUNK, 1)
    )


def osv_vuln_docs() -> st.SearchStrategy[dict[str, Any]]:
    """OSV vulnerability documents, to be queried for ``QUERY_ECOSYSTEM``/``QUERY_NAME``.

    * several ``affected`` entries, in several ecosystems, with the queried name in several
      spellings that are equal after PEP 503 normalisation, and near misses that are not;
    * ``SEMVER``, ``ECOSYSTEM`` and ``GIT`` ranges (GIT ranges often carry commit-hash
      ``fixed`` values that match the version pattern) and a few odd ``type`` values;
    * ``introduced``, ``fixed``, ``last_affected`` and ``limit`` events;
    * absent, empty and wrongly typed values at every level, and ``fixed`` values that are
      not strings, are empty, contain unexpected characters or are too long;
    * decoy fixes in places ``has_fix`` must ignore.

    Both fixable and unfixable documents are common for the queried package.
    """
    decoy_doc = st.builds(lambda: {"affected": [{"package": query_package(), **_decoy_fix()}]})
    return _sparse(
        {
            "id": (osv_ids(), 8),
            "modified": (_TIMESTAMPS, 5),
            "published": (_TIMESTAMPS, 5),
            "withdrawn": (_TIMESTAMPS, 1),
            "summary": (st.text(max_size=30), 4),
            "aliases": (st.lists(st.text(max_size=12), max_size=3), 4),
            "affected": (_affected_entries(), 9),
            "database_specific": (decoy_doc, 2),
        }
    )


# --- repository candidates (SRC-REPO-1..6, T5.3) -------------------------------------------

_OWNER_POOL = ("o", "O", "lodash", "Lodash", "LODASH", "Foo-Bar", "octocat", "a1")
_REPO_POOL = ("r", "R", "lodash", "Lodash", "Lodash.js", "x_y", "repo-1", "core.git-utils")
_REPO_URL_TEMPLATES = (
    "https://github.com/{o}/{r}",
    "http://github.com/{o}/{r}",
    "https://www.github.com/{o}/{r}",
    "github.com/{o}/{r}",
    "git+https://github.com/{o}/{r}.git",
    "git://github.com/{o}/{r}.git",
    "git+ssh://git@github.com/{o}/{r}.git",
    "ssh://git@github.com/{o}/{r}.git",
    "git@github.com:{o}/{r}",
    "git@github.com:{o}/{r}.git",
    "github:{o}/{r}",
    "https://github.com/{o}/{r}.git?ref=main#readme",
    "https://github.com/{o}/{r}/tree/main/docs",
    "  https://github.com/{o}/{r}  ",
)
_FOREIGN_CANDIDATES = (
    "https://gitlab.com/o/r",
    "https://bitbucket.org/o/r",
    "git+https://gitlab.com/o/r.git",
    "git@gitlab.com:o/r.git",
    "https://github.com.evil.example/o/r",
    "https://evil.example#@github.com/o/r",
    "https://example.org/",
    "https://github.com/onlyowner",
    "not a url",
    "",
)


def repo_owners() -> st.SearchStrategy[str]:
    """Plausible, non-reserved owner names, with case variants that collide on ``repo_key``."""
    return st.one_of(
        st.sampled_from(_OWNER_POOL), st.from_regex(r"[A-Za-z0-9]{1,3}", fullmatch=True)
    )


def repo_names() -> st.SearchStrategy[str]:
    return st.one_of(
        st.sampled_from(_REPO_POOL), st.from_regex(r"[A-Za-z0-9]{1,3}", fullmatch=True)
    )


@st.composite
def reserved_owners(draw: st.DrawFn) -> str:
    """A reserved GitHub path in a random mix of upper and lower case."""
    name = draw(st.sampled_from(sorted(RESERVED_OWNERS)))
    return "".join(draw(st.sampled_from((ch.lower(), ch.upper()))) for ch in name)


def _render(template: str, owner: str, repo: str) -> str:
    return template.format(o=owner, r=repo)


def repo_url_forms(owners: st.SearchStrategy[str] | None = None) -> st.SearchStrategy[str]:
    """One of the EX-9 URL forms for a generated owner and repo."""
    return st.builds(
        _render,
        st.sampled_from(_REPO_URL_TEMPLATES),
        repo_owners() if owners is None else owners,
        repo_names(),
    )


def repo_candidates() -> st.SearchStrategy[str]:
    """Raw repository strings: valid forms, reserved-owner forms, other hosts and junk."""
    return st.one_of(
        repo_url_forms(),
        repo_url_forms(),
        repo_url_forms(reserved_owners()),
        st.sampled_from(_FOREIGN_CANDIDATES),
        st.text(max_size=40),
    )


def repo_candidate_lists(max_size: int = 5) -> st.SearchStrategy[tuple[str, ...]]:
    return st.lists(repo_candidates(), max_size=max_size).map(tuple)


def display_repos() -> st.SearchStrategy[str]:
    """``github.com/<owner>/<repo>`` display forms, drawn from pools so keys collide often."""
    return st.builds("github.com/{}/{}".format, repo_owners(), repo_names())


# --- assembly scenarios (SRC-TEST-5, T6.4) ---------------------------------------------------

PURL_STRINGS = (
    "pkg:npm/x@1.0.0",
    "pkg:npm/%40a/b@2.0.0",
    "pkg:pypi/six@1.17.0",
    "pkg:pypi/flask-sqlalchemy@3.0%2Blocal",
)

_BAD_FLAGS = st.sampled_from((0, 1, 2, "true", "", [], 1.0, "deprecated"))
_BAD_COUNTS = st.sampled_from(
    (-1, -(10**30), True, False, 1.5, float("nan"), float("inf"), "3", [], date(2026, 1, 1))
)
_BAD_SCORES = st.sampled_from(
    (11, -2, 10.5, -0.5, 1e308, float("nan"), float("inf"), -float("inf"), True, False, "5", [])
)
_BAD_DAYS = st.sampled_from(
    (
        datetime(2026, 11, 3, 12, 0),
        datetime(2026, 11, 3, 12, 0, tzinfo=UTC),
        "2026-11-03",
        20261103,
        1.5,
        [],
    )
)
_BAD_VERSIONS = st.sampled_from(("", "not valid!", " 1.0", "1.0\n", "x" * 101, 5, ["1.0"], True))
_URL_STRINGS = st.one_of(
    st.sampled_from(
        (
            "https://api.deps.dev/v3/systems/npm/packages/x",
            "https://registry.npmjs.org/x",
            "https://api.github.com/graphql",
            "https://example.org/a?b=c",
        )
    ),
    # Foreign text is allowed, but not text that is only a credential: ``strip_userinfo("@")`` is
    # "", and a value with no origin would break "a value has a source URL" (SRC-API-3). Every URL
    # a client passes comes from a ``core.sources.urls`` builder, never such text (SRC-SEC-3).
    st.text(min_size=1, max_size=30).filter(strip_userinfo),
    token_shapes().map("https://example.org/{}".format),
)


def messy_flags() -> st.SearchStrategy[Any]:
    """``None``, a ``bool``, or a value that is not a ``bool``."""
    return _weighted((st.none(), 3), (st.booleans(), 6), (_BAD_FLAGS, 1))


def messy_counts() -> st.SearchStrategy[Any]:
    """``None``, a count (huge ones too), or a negative, ``bool``, float, ``NaN`` or string."""
    valid = st.one_of(
        st.integers(0, 10**6), st.integers(10**30, 10**60), st.just(10**400), st.just(0)
    )
    return _weighted((st.none(), 3), (valid, 6), (_BAD_COUNTS, 3))


def messy_scores() -> st.SearchStrategy[Any]:
    """``None``, a score in [0, 10] or -1, or a value outside the domain."""
    valid = st.one_of(fact_scores(), st.integers(0, 10), st.just(-1))
    return _weighted((st.none(), 3), (valid, 6), (_BAD_SCORES, 3))


def messy_days() -> st.SearchStrategy[Any]:
    """``None``, a ``date``, or a ``datetime``, string or number in its place."""
    return _weighted((st.none(), 3), (fact_dates(), 6), (_BAD_DAYS, 2))


def messy_versions() -> st.SearchStrategy[Any]:
    return _weighted((st.none(), 3), (version_strings(), 6), (_BAD_VERSIONS, 2))


def messy_bools() -> st.SearchStrategy[Any]:
    """A required ``bool`` that is sometimes something else."""
    return _weighted((st.booleans(), 8), (_BAD_FLAGS, 1))


def _messy_depsdev_versions() -> st.SearchStrategy[DepsDevVersion]:
    return st.builds(
        DepsDevVersion,
        is_deprecated=messy_flags(),
        published_at=messy_days(),
        repo_candidates=st.just(()),
    )


def _messy_depsdev_packages() -> st.SearchStrategy[DepsDevPackage]:
    return st.builds(DepsDevPackage, default_version=messy_versions())


def _messy_depsdev_projects() -> st.SearchStrategy[DepsDevProject]:
    return st.builds(
        DepsDevProject,
        maintained=messy_scores(),
        overall=messy_scores(),
        has_scorecard=messy_bools(),
    )


def _messy_npm_registries() -> st.SearchStrategy[NpmRegistry]:
    return st.builds(
        NpmRegistry,
        latest=messy_versions(),
        latest_deprecated=messy_flags(),
        resolved_deprecated=messy_flags(),
        resolved_found=_weighted((st.just(True), 6), (st.just(False), 2), (_BAD_FLAGS, 1)),
    )


def _messy_npm_fulls() -> st.SearchStrategy[NpmFull]:
    return st.builds(NpmFull, latest_published=messy_days(), repo_candidates=st.just(()))


def _messy_pypi_docs() -> st.SearchStrategy[PypiDoc]:
    return st.builds(
        PypiDoc,
        latest=messy_versions(),
        latest_published=messy_days(),
        resolved_found=_weighted(
            (st.none(), 2), (st.just(True), 5), (st.just(False), 2), (_BAD_FLAGS, 1)
        ),
        repo_candidates=st.just(()),
    )


def _messy_downloads() -> st.SearchStrategy[Downloads]:
    return st.builds(Downloads, weekly=messy_counts())


def _messy_github_repos() -> st.SearchStrategy[GitHubRepo]:
    return st.builds(
        GitHubRepo,
        is_archived=messy_flags(),
        pushed_at=messy_days(),
        open_issues=messy_counts(),
        closed_issues=messy_counts(),
        committers=messy_counts(),
        committers_lower_bound=messy_bools(),
        found=_weighted((st.just(True), 7), (st.just(False), 2), (_BAD_FLAGS, 1)),
    )


def _messy_osv_vulns() -> st.SearchStrategy[Any]:
    """An ``OsvVuln`` with fields that are sometimes wrong, or something that is not one."""
    broken = st.builds(
        OsvVuln,
        id=_weighted((osv_ids(), 6), (st.sampled_from(("", "bad id!", "a" * 101, 5, None)), 2)),
        withdrawn=messy_bools(),
        published_at=messy_days(),
        fixed_versions=_weighted(
            (st.lists(version_strings(), max_size=3).map(tuple), 5),
            (st.sampled_from((["1.0"], ("not valid!",), "1.0", None, (1,))), 2),
        ),
        has_fix=messy_bools(),
    )
    return _weighted(
        (osv_vulns(), 8), (broken, 3), (st.sampled_from((None, "GHSA-aaaa", {}, 7)), 1)
    )


@st.composite
def _messy_osv_facts(draw: st.DrawFn) -> Any:
    vulns = draw(st.lists(_messy_osv_vulns(), max_size=4))
    return list(vulns) if draw(st.integers(0, 9)) == 0 else tuple(vulns)


def _sourced(fact: st.SearchStrategy[Any]) -> st.SearchStrategy[Sourced[Any] | None]:
    """A ``Sourced`` fact (always valid: URL non-empty, fetch time UTC) or ``None``."""
    moments = st.datetimes(timezones=st.sampled_from((UTC, timezone(timedelta(0)))))
    built = st.builds(
        Sourced,
        fact,
        _URL_STRINGS,
        moments,
        st.lists(_URL_STRINGS, max_size=2).map(tuple),
    )
    return _weighted((st.none(), 2), (built, 8))


@st.composite
def messy_package_facts(draw: st.DrawFn) -> PackageFacts:
    """Facts for ``assemble`` with fields that are sometimes missing, wrong or out of domain."""
    return PackageFacts(
        registry_npm=draw(_sourced(_messy_npm_registries())),
        registry_pypi=draw(_sourced(_messy_pypi_docs())),
        npm_full=draw(_sourced(_messy_npm_fulls())),
        depsdev_resolved=draw(_sourced(_messy_depsdev_versions())),
        depsdev_latest=draw(_sourced(_messy_depsdev_versions())),
        depsdev_package=draw(_sourced(_messy_depsdev_packages())),
        project=draw(_sourced(_messy_depsdev_projects())),
        scorecard=draw(_sourced(_messy_depsdev_projects())),
        osv=draw(_sourced(_messy_osv_facts())),
        github=draw(_sourced(_messy_github_repos())),
        absent=draw(st.frozensets(st.sampled_from(sorted(FEEDS)), max_size=3)),
    )


def failures() -> st.SearchStrategy[Failure]:
    """A ``Failure`` as a client would record it (any code, any source but ``internal``)."""
    return st.builds(
        Failure,
        code=st.sampled_from(sorted(WARNING_CODES)),
        source=st.sampled_from(sorted(SOURCE_NAMES - {"internal"})),
        status=st.one_of(st.none(), st.integers(100, 599)),
        feeds=st.lists(st.sampled_from(EVIDENCE_KEYS), max_size=4).map(tuple),
        url=st.one_of(st.none(), _URL_STRINGS),
    )


def _downloads_states() -> st.SearchStrategy[DownloadsState]:
    found = _sourced(_messy_downloads()).map(
        lambda sourced: Found(sourced) if sourced is not None else Absent()
    )
    return _weighted(
        (found, 8),
        (st.builds(Absent, url=st.one_of(st.none(), _URL_STRINGS)), 1),
        (
            st.builds(
                Failed,
                kind=st.sampled_from(sorted(WARNING_CODES)),
                status=st.one_of(st.none(), st.integers(100, 599)),
                url=st.one_of(st.none(), _URL_STRINGS),
            ),
            1,
        ),
        (st.just(Skipped()), 1),
        (st.just(Deferred()), 1),
    )


def _repo_infos() -> st.SearchStrategy[RepoInfo]:
    with_repo = st.builds(
        RepoInfo,
        repo=st.just("github.com/o/r"),
        via=st.sampled_from(("depsdev", "registry", "project_urls")),
    )
    return _weighted((st.just(RepoInfo()), 1), (with_repo, 3))


@dataclass(frozen=True)
class Scenario:
    """Everything one call of ``assemble`` takes."""

    purl: Purl
    as_of: date
    facts: PackageFacts
    failures: tuple[Failure, ...]
    repo_info: RepoInfo
    downloads: DownloadsState


def package_scenarios() -> st.SearchStrategy[Scenario]:
    """Well-formed and malformed inputs for ``assemble`` across all sources (SRC-TEST-5)."""
    return st.builds(
        Scenario,
        purl=st.sampled_from(PURL_STRINGS).map(parse_purl),
        as_of=st.dates(),
        facts=messy_package_facts(),
        failures=st.lists(failures(), max_size=4).map(tuple),
        repo_info=_repo_infos(),
        downloads=_downloads_states(),
    )


# --- signals for the Resting-candidate property (SRC-TEST-15) --------------------------------


@st.composite
def scoring_signals(draw: st.DrawFn) -> Signals:
    """Valid ``Signals`` spread over the Alive, Ailing, Resting and Dead bands.

    Ages run from 0 to about five years, so the staleness risks cover [0, 1]. S7 is unknown,
    known empty or non-empty; S9 is anything, including values on both sides of the threshold.
    """
    as_of = draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))

    def day() -> date | None:
        if draw(st.integers(0, 9)) == 0:
            return None
        return as_of - timedelta(days=draw(st.integers(-30, 1800)))

    def score() -> float | None:
        result: float | None = draw(
            _weighted((st.none(), 2), (st.floats(0, 10), 7), (st.just(-1.0), 1))
        )
        return result

    def count(high: int) -> int | None:
        result: int | None = draw(_weighted((st.none(), 2), (st.integers(0, high), 8)))
        return result

    advisory = st.builds(
        Advisory,
        id=osv_ids(),
        has_fix=st.booleans(),
        published_at=_optional(st.dates(min_value=date(2015, 1, 1), max_value=as_of)),
    )
    return Signals(
        purl="pkg:pypi/x@1.0.0",
        as_of=as_of,
        s1_declared_death=draw(_weighted((st.none(), 2), (st.just(False), 7), (st.just(True), 1))),
        s1b_version_deprecated=draw(st.one_of(st.none(), st.booleans())),
        s2_latest_release_at=day(),
        s3_last_push_at=day(),
        s4_maintained=score(),
        s5_committers=count(30),
        s6_open_issues=count(100),
        s6_closed_issues=count(300),
        s7_advisories=draw(
            _weighted(
                (st.none(), 2),
                (st.just(()), 6),
                (st.lists(advisory, min_size=1, max_size=2).map(tuple), 2),
            )
        ),
        s8_overall=score(),
        s9_weekly_downloads=draw(
            _weighted((st.none(), 2), (st.integers(0, 40_000), 4), (st.integers(0, 10**9), 2))
        ),
    )


@st.composite
def weights_variants(draw: st.DrawFn) -> Weights:
    """The packaged v1 weights, or the same weights with other thresholds."""
    base = load_weights()
    if draw(st.booleans()):
        return base
    ailing = draw(st.floats(0, 100))
    return replace(
        base,
        threshold_ailing=ailing,
        threshold_dead=draw(st.floats(ailing, 100)),
        threshold_resting_r6_max=draw(st.floats(0, 1)),
        resting_min_weekly_downloads=draw(
            _weighted((st.just(base.resting_min_weekly_downloads), 2), (st.integers(0, 10**6), 3))
        ),
    )
