"""Exhaustive single-leaf and pair sweeps over the fake web (SRC-TEST-6, D17).

``test_failures_only_degrade`` and the single-leaf properties sample the space of damaged
responses. This file walks it: for a few small generated worlds it records every response of a
clean run, then gives **each leaf of each response**, one at a time, a value of another type
(``wrong_one_leaf``, on every attempt so that a retry cannot hide it), and checks the same
invariant as the properties (``assert_only_degrades``): a signal is the clean value, or ``None``
with a warning or an upstream-absence note, and nothing raises.

The pair sweep does the same for every pair of leaves on two different requests. It found what
random sampling needed luck for: a signal with two sources (S2: deps.dev ``publishedAt`` and the
registry ``time[latest]``) became ``None`` with no warning when both were damaged.

The sweeps are deterministic (no Hypothesis, no randomness beyond the world seed) and cheap,
about 5 ms per run. A failure names the request, the leaf path and the signal.

Known limit, recorded in design §14: the invariant accepts "upstream has nothing" notes such as
"Scorecard has no Maintained check" as an explanation, as SRC-TEST-6 allows. Without that
allowance the same sweep also reports a damaged Scorecard score and a damaged repo candidate
(``info.home_page``, ``repository.url``) as silent absences.
"""

from __future__ import annotations

import contextlib
import json
from itertools import combinations
from typing import Any

import httpx
import pytest

from core.sources.model import BatchResult
from sources.tests.strategies import PackageSet
from sources.tests.test_properties_session import assert_only_degrades, run_collect
from sources.tests.transports import ALWAYS, Fault, fault_transport, key_of, leaf_paths

type Site = tuple[str, str, int, tuple[str | int, ...]]
"""``(request key, url, leaf index, leaf path)``."""


def _label(site: Site) -> str:
    _, url, _, path = site
    shape = ".".join("[]" if isinstance(step, int) else step for step in path)
    return f"{url.split('/', 3)[2]} {url.split('/', 3)[3][:60]} :: {shape}"


def _record(
    ps: PackageSet, plan: dict[str, Fault] | None = None
) -> tuple[list[Site], BatchResult, list[tuple[Any, Any]]]:
    """Run the world (optionally with ``plan``), recording every response the web served.

    Returns the leaves of those responses (the sites to damage), the batch result and the
    inputs. The recording sits below the fault transport, so it sees the undamaged upstream
    answers. With no plan this is the clean run.
    """
    web = ps.web()
    bodies: dict[str, tuple[str, object]] = {}

    async def capture(request: httpx.Request) -> httpx.Response:
        response = await web.handler(request)
        with contextlib.suppress(ValueError):
            bodies[key_of(request)] = (str(request.url), json.loads(response.content))
        return response

    transport = httpx.MockTransport(capture) if not plan else fault_transport(capture, plan)
    result = run_collect(transport, web.inputs)
    sites: list[Site] = []
    for key, (url, body) in sorted(bodies.items()):
        for index, path in enumerate(leaf_paths(body)):
            sites.append((key, url, index, path))
    return sites, result, list(web.inputs)


def _clean_run(ps: PackageSet) -> tuple[list[Site], BatchResult, list[tuple[Any, Any]]]:
    return _record(ps)


def _check(
    ps: PackageSet, clean: BatchResult, plan: dict[str, Fault], inputs: list[tuple[Any, Any]]
) -> None:
    faulty_web = ps.web()
    faulty = run_collect(fault_transport(faulty_web.handler, plan), inputs)
    assert_only_degrades(faulty_web, clean, faulty, inputs)


def _fault(site: Site) -> dict[str, Fault]:
    key, _, index, _ = site
    return {key: Fault("wrong_one_leaf", ALWAYS, leaf=index)}


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_single_damaged_leaf_only_degrades(seed: int) -> None:
    ps = PackageSet(seed=seed, size=3)
    sites, clean, inputs = _clean_run(ps)
    assert len(sites) > 100  # the world has enough leaves for the sweep to mean something
    failures: list[str] = []
    for site in sites:
        try:
            _check(ps, clean, _fault(site), inputs)
        except AssertionError as exc:
            failures.append(f"{_label(site)}: {str(exc)[:160]}")
    assert failures == []


@pytest.mark.parametrize("seed", [1, 2])
def test_every_pair_of_damaged_leaves_on_two_requests_only_degrades(seed: int) -> None:
    ps = PackageSet(seed=seed, size=1)
    sites, clean, inputs = _clean_run(ps)
    assert 20 < len(sites) < 400  # small enough for all pairs, big enough to matter
    failures: list[str] = []
    for first, second in combinations(sites, 2):
        if first[0] == second[0]:
            continue  # one fault per request key
        try:
            _check(ps, clean, {**_fault(first), **_fault(second)}, inputs)
        except AssertionError as exc:
            failures.append(f"{_label(first)} + {_label(second)}: {str(exc)[:160]}")
    assert failures == []


def _is_published_at(site: Site) -> bool:
    """A deps.dev ``publishedAt`` leaf."""
    return bool(site[3]) and site[3][-1] == "publishedAt"


def _is_release_date(site: Site) -> bool:
    """A leaf that feeds S2: deps.dev ``publishedAt``, an npm ``time`` entry, a PyPI upload time."""
    path = site[3]
    return bool(path) and (
        path[-1] in ("publishedAt", "upload_time_iso_8601") or "time" in path[:1]
    )


def _fallback_sites(ps: PackageSet, published: list[Site]) -> list[Site]:
    """The ``time`` leaves of the npm full packuments, which only appear as a fallback.

    A clean run never requests a full packument: deps.dev already gave ``publishedAt``. They are
    requested only when ``publishedAt`` is unusable, so record a run in which every deps.dev
    ``publishedAt`` is damaged and take the leaves of the full packuments served then.
    """
    plan = {site[0]: Fault("wrong_one_leaf", ALWAYS, leaf=site[2]) for site in published}
    sites, _, _ = _record(ps, plan)
    return [site for site in sites if site[3][:1] == ("time",)]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_every_pair_of_damaged_release_dates_only_degrades(seed: int) -> None:
    """S2 has up to three sources (deps.dev, npm ``time``, PyPI upload times).

    The pair sweep over all leaves needs minutes on a world of this size, so this one pairs only
    the leaves that feed S2, including the npm ``time`` leaves that only exist once deps.dev
    has failed. It is the case that failed before D17 reached these parsers: both sources
    damaged, S2 ``None``, no warning. A single damaged source is absorbed by the fallback,
    which is why the single-leaf sweep cannot see it.
    """
    ps = PackageSet(seed=seed, size=3)
    sites, clean, inputs = _clean_run(ps)
    published = [site for site in sites if _is_published_at(site)]
    dates = [site for site in sites if _is_release_date(site)]
    fallback = _fallback_sites(ps, published)
    assert published and fallback  # both sources of S2 exist in this world
    failures: list[str] = []
    checked = 0
    for first, second in [*combinations(dates, 2), *((p, f) for p in published for f in fallback)]:
        if first[0] == second[0]:
            continue
        checked += 1
        try:
            _check(ps, clean, {**_fault(first), **_fault(second)}, inputs)
        except AssertionError as exc:
            failures.append(f"{_label(first)} + {_label(second)}: {str(exc)[:160]}")
    assert checked > 20
    assert failures == []
