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
"""

from __future__ import annotations

import copy
import string
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from hypothesis import strategies as st

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
