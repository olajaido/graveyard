"""The nine mortality anchors, end to end over the recorded cassette (T13.3; SRC-ANC-1…5).

``autopsy_async`` runs the real session, gateway, clients and parsers on ``httpx.MockTransport``
that replays ``anchors.cassette.json`` (a maintainer-run recording of the real services at
``as_of = 2026-11-03``). Then:

* the scoring core classifies each result's ``Signals`` and the classification must equal the
  MM-ANC table (written out below) and the committed anchor fixtures;
* the signals must agree with the committed fixtures within the SRC-ANC-3 tolerances;
* every evidence URL is on the allow-list and every ``fetched_at`` lies within the run;
* the request log shows the batching the design promises.

No network, no real clock.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any, Final
from urllib.parse import urlsplit

import httpx
import pytest

from core.scoring import score_package
from core.scoring.tests.test_anchors import signals_from_fixture
from core.scoring.types import BaseState, ScoringResult
from core.scoring.weights import load_weights
from core.sources import assemble as asm
from core.sources.config import SourcesConfig
from core.sources.model import BatchResult, SourceResult
from core.sources.secret import SecretToken
from core.sources.tests import recorded as rec
from core.sources.urls import ALLOWED_HOSTS
from sources.api import autopsy_async
from sources.tests.clock import FakeClock
from sources.tests.transports import ReplayLog, replay_transport

_START: Final = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)

# MM-ANC-1…9: (base state, dead reason, cursed, wounded)
_TABLE: Final[dict[str, tuple[BaseState, str | None, bool, bool]]] = {
    "request": (BaseState.DEAD, "declared", True, False),
    "node-uuid": (BaseState.DEAD, "declared", False, False),
    "left-pad": (BaseState.DEAD, "declared", False, False),
    "express": (BaseState.ALIVE, None, False, True),
    "uuid": (BaseState.ALIVE, None, False, True),
    "moment": (BaseState.ALIVE, None, False, True),
    "pycrypto": (BaseState.DEAD, "score", True, False),
    "nose": (BaseState.DEAD, "score", False, False),
    "six": (BaseState.RESTING, None, False, False),
}


class _Run:
    def __init__(self) -> None:
        inner, self.log = replay_transport(rec.cassette())
        self.sent: list[tuple[str, str]] = []
        handler: Any = inner.handler

        def recording(request: httpx.Request) -> httpx.Response:
            self.sent.append((request.method, str(request.url)))
            result: httpx.Response = handler(request)
            return result

        self.clock = FakeClock(_START)
        self.batch: BatchResult = asyncio.run(
            autopsy_async(
                rec.anchor_requests(),
                config=SourcesConfig.default(contact="ops@example.org"),
                token=SecretToken("e2e-test-token"),
                transport=httpx.MockTransport(recording),
                clock=self.clock,
            )
        )
        self.end = self.clock.now()


@lru_cache(maxsize=1)
def _run() -> _Run:
    return _Run()


def _result(name: str) -> SourceResult:
    return _run().batch.results[rec.ANCHORS.index(name)]


def _score(result: SourceResult) -> ScoringResult:
    assert result.signals is not None
    return score_package(result.signals)


def test_the_cassette_serves_every_request() -> None:
    log: ReplayLog = _run().log
    assert log.unmatched == []
    assert len(log.matched) == len(_run().sent)


@pytest.mark.parametrize("name", rec.ANCHORS)
def test_no_item_error_and_no_warning(name: str) -> None:
    result = _result(name)
    assert result.error is None
    assert result.signals is not None
    assert result.warnings == ()
    assert result.signals.purl == rec.anchor_purl(name)


@pytest.mark.parametrize("name", rec.ANCHORS)
def test_state_matches_the_mm_anc_table_and_the_fixture(name: str) -> None:
    state, reason, cursed, wounded = _TABLE[name]
    got = _score(_result(name))
    assert (got.base_state, got.dead_reason, got.cursed, got.wounded) == (
        state,
        reason,
        cursed,
        wounded,
    )
    want = score_package(signals_from_fixture(rec.anchor_fixture(name)))
    assert (got.base_state, got.dead_reason, got.cursed, got.wounded) == (
        want.base_state,
        want.dead_reason,
        want.cursed,
        want.wounded,
    )


@pytest.mark.parametrize("name", rec.ANCHORS)
def test_exposure_is_assumed_because_no_graph_was_given(name: str) -> None:
    got = _score(_result(name))
    assert got.exposure == 1.0
    assert got.exposure_assumed is True


def test_pinned_scores() -> None:
    assert _score(_result("left-pad")).mortality == load_weights().threshold_s1_min_score
    assert _score(_result("pycrypto")).confidence == pytest.approx(0.25)
    assert _score(_result("nose")).confidence == pytest.approx(0.25)
    six = _score(_result("six"))
    assert six.mortality == pytest.approx(43.7, abs=0.5)


# --- parity with the committed fixtures (SRC-ANC-3) -------------------------------------------


def _close(got: float | int | None, want: float | int | None, tolerance: float) -> bool:
    if got is None or want is None:
        return got is want
    return abs(got - want) <= tolerance


def _days(got: date | None, want: date | None) -> bool:
    if got is None or want is None:
        return got is want
    return abs((got - want).days) <= 14


@pytest.mark.parametrize("name", rec.ANCHORS)
def test_signals_agree_with_the_committed_fixture(name: str) -> None:
    result = _result(name)
    assert result.signals is not None
    got, want = result.signals, signals_from_fixture(rec.anchor_fixture(name))
    assert _days(got.s2_latest_release_at, want.s2_latest_release_at), name
    assert _days(got.s3_last_push_at, want.s3_last_push_at), name
    assert _close(got.s4_maintained, want.s4_maintained, 0.5), name
    assert _close(got.s8_overall, want.s8_overall, 0.5), name
    assert _close(got.s5_committers, want.s5_committers, 1), name
    for got_count, want_count in (
        (got.s6_open_issues, want.s6_open_issues),
        (got.s6_closed_issues, want.s6_closed_issues),
    ):
        if got_count is not None and want_count is not None:
            assert _close(got_count, want_count, max(10, 0.05 * want_count)), name
        else:
            assert got_count is want_count, name
    skipped = result.evidence["s9_weekly_downloads"].note == asm.NOTE_S9_SKIPPED
    got_s9, want_s9 = got.s9_weekly_downloads, want.s9_weekly_downloads
    if not skipped and got_s9 is not None and want_s9 is not None:
        assert _close(got_s9, want_s9, max(1000, 0.25 * want_s9)), name
    if want.s1_declared_death is not False or got.s1_declared_death is not None:
        assert got.s1_declared_death == want.s1_declared_death, name
    assert got.s1b_version_deprecated == want.s1b_version_deprecated, name
    assert got.s7_advisories is not None and want.s7_advisories is not None
    assert sorted((a.id, a.has_fix) for a in got.s7_advisories) == sorted(
        (a.id, a.has_fix) for a in want.s7_advisories
    ), name


# --- evidence and request log -----------------------------------------------------------------


@pytest.mark.parametrize("name", rec.ANCHORS)
def test_evidence_urls_are_allow_listed_and_times_fall_inside_the_run(name: str) -> None:
    result = _result(name)
    for key, evidence in result.evidence.items():
        urls = [u for u in (evidence.source_url, *evidence.extra_source_urls) if u is not None]
        for url in urls:
            assert urlsplit(url).hostname in ALLOWED_HOSTS, (key, url)
        if evidence.fetched_at is not None:
            assert _START <= evidence.fetched_at <= _run().end, key


def test_batching_in_the_request_log() -> None:
    sent = _run().sent
    assert sent.count(("GET", rec.NPM_BULK_URL)) == 1
    assert len(rec.NPM_BULK_URL.rsplit("/", 1)[1].split(",")) == 6
    assert [url for _, url in sent if "api.npmjs.org" in url] == [rec.NPM_BULK_URL]
    assert [url for _, url in sent if "pypistats.org" in url] == [rec.PYPISTATS_SIX_URL]
    assert [m for m, url in sent if url == rec.OSV_QUERYBATCH_URL] == ["POST"]
    github_posts = [url for m, url in sent if m == "POST" and url == rec.GITHUB_URL]
    assert len(github_posts) == 1
    assert len(sent) == len(set(sent)), "no request is sent twice"


def test_stats_count_what_was_skipped() -> None:
    stats = _run().batch.stats
    assert stats.s9_skipped == 2
    assert sum(stats.failures.values()) == 0


# --- hostile text in every response (SRC-SEC-2) -----------------------------------------------


def _hostile_batch() -> BatchResult:
    def rewrite(url: str, doc: Any) -> Any:
        return rec.inject_github_authors(doc) if url == rec.GITHUB_URL else rec.inject_text(doc)

    inner, log = replay_transport(rec.with_bodies(rewrite))
    batch = asyncio.run(
        autopsy_async(
            rec.anchor_requests(),
            config=SourcesConfig.default(contact="ops@example.org"),
            token=SecretToken("e2e-test-token"),
            transport=inner,
            clock=FakeClock(_START),
        )
    )
    assert log.unmatched == []
    return batch


def test_hostile_free_text_changes_nothing_and_reaches_no_result() -> None:
    clean, hostile = _run().batch, _hostile_batch()
    for before, after in zip(clean.results, hostile.results, strict=True):
        assert after.signals == before.signals
        assert after.warnings == before.warnings
        assert {k: e.value for k, e in after.evidence.items()} == {
            k: e.value for k, e in before.evidence.items()
        }
    text = repr(hostile)
    assert "evil.example" not in text
    assert "<script>" not in text
    assert "Ignore all previous instructions" not in text
