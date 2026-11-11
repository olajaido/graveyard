"""Fault injection over the recorded anchor cassette (T13.4; SRC-TEST-6, SRC-TEST-13).

The clean run replays the cassette. A faulted run replays it through ``fault_transport``. The
invariant is the one of ``test_properties_session``: every signal of every anchor is either equal
to the clean value, or ``None`` and then explained (named by a warning, or carrying an
upstream-absence note). A fault never changes a value and never invents one.

A request the cassette has no answer for (for example a fallback that a fault newly triggers) is
a connection error, which is one more source failure, not a test failure.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx
import pytest
from hypothesis import given, settings

from core.sources.model import EVIDENCE_KEYS, BatchResult, SourceResult
from core.sources.parse import scorecard
from core.sources.tests import recorded as rec
from sources.clients.registry import NPM_ABBREVIATED_ACCEPT
from sources.tests.strategies import FAST_FAULT_KINDS, FaultPlan, fault_plans
from sources.tests.test_properties_session import TOKEN, explained, run_collect
from sources.tests.transports import ALWAYS, Fault, FaultKind, fault_transport, replay_transport

_KINDS: tuple[FaultKind, ...] = (*FAST_FAULT_KINDS, "wrong_one_leaf")


def _handler() -> tuple[Any, Any]:
    """The replay handler, minus full packuments that were never recorded.

    The cassette key ignores ``Accept``, so for most npm anchors the one recorded packument is
    the abbreviated one and would also answer a request for the full one, with no ``time`` in
    it. Real npm always sends ``time`` in a full packument. A full-packument request for such a
    package is therefore treated as unrecorded: a connection error, like any other request the
    cassette does not contain.
    """
    transport, log = replay_transport(rec.cassette())
    inner: Any = transport.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if (
            request.url.host == "registry.npmjs.org"
            and request.headers.get("accept") != NPM_ABBREVIATED_ACCEPT
            and "time" not in rec.body(str(request.url))
        ):
            raise httpx.ConnectError("full packument not recorded", request=request)
        result: httpx.Response = inner(request)
        return result

    return handler, log


@lru_cache(maxsize=1)
def _clean() -> tuple[BatchResult, tuple[str, ...]]:
    """The clean batch and the request keys it used (the fallbacks it did not need are left out)."""
    handler, log = _handler()
    batch = run_collect(httpx.MockTransport(handler), rec.anchor_requests())
    assert log.unmatched == []
    return batch, tuple(sorted(set(log.matched)))


_SCORECARD_KEYS = ("s4_maintained", "s8_overall")


def _scorecard_api_value(result: SourceResult, key: str) -> float | None:
    """What the Scorecard API (the fallback for S4 and S8) recorded for the result's repo.

    deps.dev serves Scorecard values from an older run than the API (the recording has express
    at 8.5 against 8.9), so when the deps.dev project request fails the fallback legitimately
    gives the API's own value. Anything else that differs from the clean run is a failure.
    """
    assert result.repo is not None
    card = scorecard.parse_scorecard_api(
        rec.body(f"https://api.securityscorecards.dev/projects/{result.repo}")
    )
    assert card is not None
    return card.maintained if key == "s4_maintained" else card.overall


def _check(faulty: BatchResult) -> None:
    clean, _ = _clean()
    assert len(faulty.results) == len(clean.results) == len(rec.ANCHORS)
    assert TOKEN not in repr(faulty)
    for before, after in zip(clean.results, faulty.results, strict=True):
        assert before.signals is not None and after.signals is not None
        assert after.error is None
        for key in EVIDENCE_KEYS:
            was = getattr(before.signals, key)
            now = getattr(after.signals, key)
            where = (after.input_purl, key, was, now)
            if now is None:
                if was is not None:
                    assert explained(after, key), (*where, after.evidence[key])
            elif now != was:
                assert key in _SCORECARD_KEYS and now == _scorecard_api_value(after, key), where


def _faulty(plan: dict[str, Fault]) -> BatchResult:
    handler, _ = _handler()
    return run_collect(fault_transport(handler, plan), rec.anchor_requests())


def test_the_clean_run_has_no_warning() -> None:
    clean, keys = _clean()
    assert all(r.warnings == () for r in clean.results)
    assert len(keys) == 42


@pytest.mark.parametrize(
    "fault",
    [
        Fault("status", ALWAYS, status=503),
        Fault("status", ALWAYS, status=404),
        Fault("truncated_body", ALWAYS),
        Fault("wrong_field_types", ALWAYS),
        Fault("wrong_one_leaf", ALWAYS, leaf=0),
        Fault("wrong_one_leaf", ALWAYS, leaf=7),
        Fault("null_body", ALWAYS),
    ],
    ids=lambda f: f"{f.kind}-{f.status if f.kind == 'status' else f.leaf}",
)
def test_each_recorded_request_failing_alone_only_degrades(fault: Fault) -> None:
    _, keys = _clean()
    for key in keys:
        _check(_faulty({key: fault}))


def test_every_recorded_request_failing_at_once_degrades_without_error() -> None:
    _, keys = _clean()
    _check(_faulty({key: Fault("status", ALWAYS, status=503) for key in keys}))


@pytest.mark.property
@settings(deadline=None)  # each example replays nine packages through the full session
@given(plan=fault_plans(max_faults=10, kinds=_KINDS))
def test_random_faults_over_the_cassette_only_degrade(plan: FaultPlan) -> None:
    """**Validates: Requirements SRC-TEST-6, SRC-TEST-13**"""
    _, keys = _clean()
    _check(_faulty(plan.resolve(keys)))
