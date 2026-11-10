"""Property tests for ``core.sources.assemble`` (T6.4).

* SRC-TEST-9: S1 and S1b equal a truth-table oracle (``oracles.s1_oracle`` / ``s1b_oracle``).
* SRC-TEST-5, SRC-API-6: for any mix of well-formed and malformed facts, ``assemble`` returns
  a valid ``Signals``, evidence that is JSON-serialisable, and never needs the repair path.
* D5, SRC-API-3: a fact that is ``None`` (or unusable) never becomes ``0`` or ``False``.
* SRC-API-7: the result does not depend on the order of ``failures``.

The facts are built directly (``strategies.package_scenarios``), so wrong types, out-of-domain
numbers, ``bool`` where an ``int`` is wanted, ``NaN``, bad advisories and bad versions are all
common. Profiles come from ``conftest.py`` via ``HYPOTHESIS_PROFILE``.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta, timezone
from itertools import product
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.purl import format_purl, parse_purl
from core.scoring.types import Advisory, Signals
from core.sources.assemble import (
    Deferred,
    Found,
    PackageFacts,
    RepoInfo,
    Sourced,
    assemble,
    k_and,
    k_not,
    k_or,
)
from core.sources.facts import DepsDevVersion, Downloads, GitHubRepo, NpmRegistry, PypiDoc
from core.sources.model import EVIDENCE_KEYS, Evidence, SourceWarning
from core.sources.tests.oracles import s1_oracle, s1b_oracle
from core.sources.tests.strategies import PURL_STRINGS, Scenario, package_scenarios
from core.sources.tests.test_assemble import check_invariants, check_warnings

pytestmark = pytest.mark.property

AS_OF = date(2026, 11, 3)
AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
REPO = RepoInfo("github.com/o/r", "depsdev")
TRIPLE: tuple[bool | None, ...] = (True, False, None)

type Out = tuple[Signals, Mapping[str, Evidence], tuple[SourceWarning, ...]]


def call(sc: Scenario, failures: tuple[Any, ...] | None = None) -> Out:
    return assemble(
        sc.purl,
        sc.as_of,
        sc.facts,
        sc.failures if failures is None else failures,
        sc.repo_info,
        sc.downloads,
    )


# --- SRC-TEST-9: Kleene logic ------------------------------------------------------------

_REPO_MODES = ("found", "no_repo", "github_unavailable", "repo_not_found")
_CELL = st.sampled_from((True, False, None, "absent"))


def _flag(cell: bool | None | str) -> bool | None:
    return None if cell == "absent" else (cell if isinstance(cell, bool) else None)


def _first(a: bool | None, b: bool | None) -> bool | None:
    """The chain of SRC-S1: the deps.dev flag when it is a ``bool``, else the registry's."""
    return a if a is not None else b


def _s1_inputs(
    eco: str,
    dd_res: bool | None | str,
    dd_lat: bool | None | str,
    reg_res: bool | None,
    reg_lat: bool | None,
    mode: str,
    archived: bool | None,
) -> tuple[PackageFacts, RepoInfo]:
    """Facts for one cell of the truth table; a cell of ``"absent"`` leaves the document out."""
    base = "pkg:npm/x" if eco == "npm" else "pkg:pypi/x"

    def doc(cell: bool | None | str, url: str) -> Sourced[DepsDevVersion] | None:
        if cell == "absent":
            return None
        return Sourced(DepsDevVersion(_flag(cell), None, ()), f"{base}/{url}", AT)

    repo_fact = GitHubRepo(archived, date(2026, 10, 1), 1, 1, 1, False, mode != "repo_not_found")
    if mode == "repo_not_found":
        repo_fact = GitHubRepo(archived, None, None, None, None, False, False)
    facts = PackageFacts(
        registry_npm=(
            Sourced(NpmRegistry("2.0.0", reg_lat, reg_res, True), "https://registry.example/x", AT)
            if eco == "npm"
            else None
        ),
        registry_pypi=(
            Sourced(PypiDoc("2.0.0", date(2026, 1, 1), True, ()), "https://pypi.example/x", AT)
            if eco == "pypi"
            else None
        ),
        depsdev_resolved=doc(dd_res, "resolved"),
        depsdev_latest=doc(dd_lat, "latest"),
        github=None if mode == "github_unavailable" else Sourced(repo_fact, "https://gh", AT),
    )
    return facts, (RepoInfo() if mode == "no_repo" else REPO)


def _check_kleene_cell(
    eco: str,
    dd_res: bool | None | str,
    dd_lat: bool | None | str,
    reg_res: bool | None,
    reg_lat: bool | None,
    mode: str,
    archived: bool | None,
) -> None:
    facts, repo = _s1_inputs(eco, dd_res, dd_lat, reg_res, reg_lat, mode, archived)
    signals, evidence, _ = assemble(
        parse_purl(f"pkg:{eco}/x@1.0.0"), AS_OF, facts, (), repo, Deferred()
    )
    latest = _first(_flag(dd_lat), reg_lat) if eco == "npm" else None
    resolved = _first(_flag(dd_res), reg_res) if eco == "npm" else None
    repo_archived = archived if mode == "found" else None
    want_s1 = s1_oracle(eco, latest, repo_archived)
    want_s1b = s1b_oracle(eco, resolved, latest)
    cell = (eco, dd_res, dd_lat, reg_res, reg_lat, mode, archived)
    assert signals.s1_declared_death is want_s1, cell
    assert signals.s1b_version_deprecated is want_s1b, cell
    assert evidence["s1_declared_death"].value is want_s1, cell
    assert evidence["s1b_version_deprecated"].value is want_s1b, cell


@given(
    eco=st.sampled_from(("npm", "pypi")),
    dd_res=_CELL,
    dd_lat=_CELL,
    reg_res=st.sampled_from(TRIPLE),
    reg_lat=st.sampled_from(TRIPLE),
    mode=st.sampled_from(_REPO_MODES),
    archived=st.sampled_from(TRIPLE),
)
def test_kleene_matches_truth_table(
    eco: str,
    dd_res: bool | None | str,
    dd_lat: bool | None | str,
    reg_res: bool | None,
    reg_lat: bool | None,
    mode: str,
    archived: bool | None,
) -> None:
    """SRC-TEST-9: S1 and S1b equal the truth-table oracle for every ecosystem, every source of
    the deprecation flags, and every state of the GitHub repo."""
    _check_kleene_cell(eco, dd_res, dd_lat, reg_res, reg_lat, mode, archived)


def test_kleene_matches_truth_table_exhaustively() -> None:
    """Every ``{True, False, None}`` combination of the three parts, for both ecosystems."""
    for eco, res, lat, archived in product(("npm", "pypi"), TRIPLE, TRIPLE, TRIPLE):
        _check_kleene_cell(eco, res, lat, None, None, "found", archived)
        _check_kleene_cell(eco, "absent", "absent", res, lat, "found", archived)


@given(a=st.sampled_from(TRIPLE), b=st.sampled_from(TRIPLE))
def test_kleene_operators_match_the_completion_oracle(a: bool | None, b: bool | None) -> None:
    """The three operators agree with the enumeration oracle (they are what S1/S1b are made of)."""
    assert k_or(a, b) is s1_oracle("npm", a, b)
    assert k_and(a, k_not(b)) is s1b_oracle("npm", a, b)
    assert k_not(k_not(a)) is a


# --- SRC-TEST-5: Signals always validate --------------------------------------------------


def _in_domain(signals: Signals) -> None:
    """Restates the domains of SRC-API-6 without calling ``Signals.__post_init__``."""
    for name in ("s1_declared_death", "s1b_version_deprecated"):
        value: Any = getattr(signals, name)
        assert value is None or isinstance(value, bool), name
    for name in ("s2_latest_release_at", "s3_last_push_at"):
        value = getattr(signals, name)
        assert value is None or (isinstance(value, date) and not isinstance(value, datetime)), name
    for name in ("s5_committers", "s6_open_issues", "s6_closed_issues", "s9_weekly_downloads"):
        value = getattr(signals, name)
        assert value is None or (type(value) is int and value >= 0), (name, value)
    for name in ("s4_maintained", "s8_overall"):
        value = getattr(signals, name)
        assert value is None or (
            type(value) is float and (value == -1 or (math.isfinite(value) and 0 <= value <= 10))
        ), (name, value)
    advisories = signals.s7_advisories
    assert advisories is None or (
        isinstance(advisories, tuple) and all(isinstance(a, Advisory) for a in advisories)
    )
    assert signals.paths is None
    assert signals.services_affected is None
    assert signals.shared_repo is False


@given(sc=package_scenarios())
def test_signals_always_validate(sc: Scenario) -> None:
    """SRC-TEST-5, SRC-API-6: ``assemble`` never raises for the content of the facts; the
    ``Signals`` is in domain and re-validates; the repair path (a warning from source
    ``internal``) is never needed; evidence and warnings keep their invariants."""
    signals, evidence, warnings = call(sc)
    assert replace(signals) == signals  # runs Signals.__post_init__ again
    _in_domain(signals)
    assert not [w for w in warnings if w.source == "internal"]
    assert signals.purl == format_purl(sc.purl)
    assert signals.as_of == sc.as_of
    check_invariants(signals, evidence)
    check_warnings(evidence, warnings)


@given(
    moment=st.one_of(
        st.datetimes(),
        st.datetimes(timezones=st.just(UTC)),
        st.datetimes(
            timezones=st.builds(
                lambda minutes: timezone(timedelta(minutes=minutes)), st.integers(-1439, 1439)
            )
        ),
    )
)
def test_sourced_accepts_exactly_utc_times(moment: datetime) -> None:
    """Naive times and non-zero offsets are a caller bug (``ValueError``); only UTC is kept."""
    if moment.utcoffset() == timedelta(0):
        assert Sourced(1, "https://example.org", moment).fetched_at == moment
    else:
        with pytest.raises(ValueError, match="UTC"):
            Sourced(1, "https://example.org", moment)


# --- evidence is JSON ---------------------------------------------------------------------


@given(sc=package_scenarios())
def test_evidence_json_serialisable(sc: Scenario) -> None:
    """SRC-TEST-5: every evidence value (and the whole evidence and warning set) survives a strict
    JSON round trip."""
    _, evidence, warnings = call(sc)
    payload = {
        key: {
            "value": ev.value,
            "source_url": ev.source_url,
            "fetched_at": None if ev.fetched_at is None else ev.fetched_at.isoformat(),
            "extra_source_urls": list(ev.extra_source_urls),
            "note": ev.note,
        }
        for key, ev in evidence.items()
    }
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text) == payload
    assert list(payload) == list(EVIDENCE_KEYS)
    json.dumps([asdict(w) for w in warnings], allow_nan=False)


# --- a missing fact never becomes 0 or False ----------------------------------------------


def _usable_flag(x: object) -> bool | None:
    return x if isinstance(x, bool) else None


def _usable_count(x: object) -> int | None:
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None


def _usable_score(x: object) -> float | None:
    if isinstance(x, bool) or not isinstance(x, int | float):
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x if x == -1 or 0 <= x <= 10 else None


def _usable_day(x: object) -> date | None:
    return x if isinstance(x, date) and not isinstance(x, datetime) else None


def missing_signals(sc: Scenario) -> set[str]:
    """Signals that must be ``None`` because no input that feeds them holds a usable value.

    A value of the wrong type or outside its domain counts as missing. The one exception to
    "missing stays missing" is Kleene: ``None AND False`` is ``False``, so S1b is only listed when
    the latest version is not known to be deprecated (``NOT latest`` would then be ``False``).
    """
    facts, npm, repo = sc.facts, sc.purl.ecosystem == "npm", sc.repo_info.repo is not None
    gh: GitHubRepo | None = None
    if repo and facts.github is not None and facts.github.fact.found is True:
        gh = facts.github.fact
    out: set[str] = set()

    archived = None if gh is None else _usable_flag(gh.is_archived)
    latest: list[bool | None] = []
    resolved: list[bool | None] = []
    if facts.depsdev_latest is not None:
        latest.append(_usable_flag(facts.depsdev_latest.fact.is_deprecated))
    if facts.depsdev_resolved is not None:
        resolved.append(_usable_flag(facts.depsdev_resolved.fact.is_deprecated))
    if facts.registry_npm is not None:
        latest.append(_usable_flag(facts.registry_npm.fact.latest_deprecated))
        resolved.append(_usable_flag(facts.registry_npm.fact.resolved_deprecated))
    known_latest = [v for v in latest if v is not None]
    known_resolved = [v for v in resolved if v is not None]
    if archived is None and not (npm and known_latest):
        out.add("s1_declared_death")
    if not npm or (not known_resolved and True not in known_latest):
        out.add("s1b_version_deprecated")

    s2: list[object] = []
    if facts.depsdev_latest is not None:
        s2.append(facts.depsdev_latest.fact.published_at)
    if npm and facts.npm_full is not None:
        s2.append(facts.npm_full.fact.latest_published)
    if not npm and facts.registry_pypi is not None:
        s2.append(facts.registry_pypi.fact.latest_published)
    if not any(_usable_day(x) for x in s2):
        out.add("s2_latest_release_at")

    for key, raw, usable in (
        ("s3_last_push_at", None if gh is None else gh.pushed_at, _usable_day),
        ("s5_committers", None if gh is None else gh.committers, _usable_count),
        ("s6_open_issues", None if gh is None else gh.open_issues, _usable_count),
        ("s6_closed_issues", None if gh is None else gh.closed_issues, _usable_count),
    ):
        if usable(raw) is None:
            out.add(key)

    cards = [d.fact for d in (facts.project, facts.scorecard) if d is not None]
    if not repo or all(_usable_score(c.maintained) is None for c in cards):
        out.add("s4_maintained")
    if not repo or all(_usable_score(c.overall) is None for c in cards):
        out.add("s8_overall")

    if facts.osv is None:
        out.add("s7_advisories")

    dl = sc.downloads
    if not isinstance(dl, Found) or _usable_count(dl.data.fact.weekly) is None:
        out.add("s9_weekly_downloads")
    return out


@given(sc=package_scenarios())
def test_missing_is_never_zero(sc: Scenario) -> None:
    """D5: where every input is ``None`` or unusable the signal is ``None``: never ``0``, ``False``,
    ``()`` or a default. (``None AND False`` is ``False`` in Kleene logic and is not listed.)"""
    signals, evidence, _ = call(sc)
    for key in missing_signals(sc):
        assert getattr(signals, key) is None, key
        assert evidence[key].value is None, key


def test_missing_oracle_is_not_vacuous() -> None:
    """The oracle lists all signals for empty facts and none of the Kleene exceptions wrongly."""
    sc = Scenario(parse_purl(PURL_STRINGS[0]), AS_OF, PackageFacts(), (), REPO, Deferred())
    assert missing_signals(sc) == set(EVIDENCE_KEYS)
    assert all(getattr(call(sc)[0], k) is None for k in EVIDENCE_KEYS)
    # S1b: resolved unknown but latest deprecated -> NOT latest is False -> S1b is False.
    facts = PackageFacts(
        depsdev_latest=Sourced(DepsDevVersion(True, None, ()), "https://d/latest", AT)
    )
    kleene = replace(sc, facts=facts)
    assert "s1b_version_deprecated" not in missing_signals(kleene)
    assert call(kleene)[0].s1b_version_deprecated is False
    downloads = Found(Sourced(Downloads(None), "https://d/dl", AT))
    assert "s9_weekly_downloads" in missing_signals(replace(sc, downloads=downloads))


# --- order of failures --------------------------------------------------------------------


@given(sc=package_scenarios(), rng=st.randoms(use_true_random=False))
def test_assemble_deterministic_under_failure_order(sc: Scenario, rng: random.Random) -> None:
    """SRC-API-7: the same inputs give the same output on a repeat call, with ``failures``
    shuffled, and with every failure recorded twice."""
    base = call(sc)
    shuffled = list(sc.failures)
    rng.shuffle(shuffled)
    for variant in (sc.failures, tuple(shuffled), (*sc.failures, *shuffled)):
        again = call(sc, variant)
        assert again[0] == base[0]
        assert dict(again[1]) == dict(base[1])
        assert again[2] == base[2]
