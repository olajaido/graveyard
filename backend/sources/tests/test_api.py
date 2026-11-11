"""Public entry point tests for T10.3: re-exports, ``autopsy_async``, ``autopsy`` (SRC-API-1).

Small by design; T10.5 adds the larger cases. The hand-written ``Web`` routing table and
``left_pad_routes`` come from ``test_session``.
"""

from __future__ import annotations

import asyncio
import gc
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

import sources
from core.sources.config import Limits, SourcesConfig
from core.sources.model import BatchResult
from core.sources.secret import SecretToken
from sources import api, cache, clock, session
from sources.tests.clients_support import config
from sources.tests.clock import FakeClock
from sources.tests.fakeweb import check_batch, fakeweb
from sources.tests.test_session import AS_OF, LEFT_PAD, TOKEN_TEXT, Web, left_pad_routes

REQUESTS = [(LEFT_PAD, AS_OF)]


def _kwargs(cfg: SourcesConfig) -> dict[str, Any]:
    """Fresh transport and clock per call: each run starts from the same state."""
    return {
        "config": cfg,
        "transport": httpx.MockTransport(Web(left_pad_routes())),
        "clock": FakeClock(),
    }


def test_reexports_are_the_defining_objects() -> None:
    assert sources.autopsy is api.autopsy
    assert sources.autopsy_async is api.autopsy_async
    assert sources.SourceSession is session.SourceSession
    assert sources.SourceCache is cache.SourceCache
    assert sources.MemoryCache is cache.MemoryCache
    assert sources.SystemClock is clock.SystemClock


def test_all_lists_exactly_the_public_names() -> None:
    expected = {
        "autopsy",
        "autopsy_async",
        "SourceSession",
        "SourceCache",
        "MemoryCache",
        "SystemClock",
    }
    assert set(sources.__all__) == expected
    assert all(hasattr(sources, name) for name in sources.__all__)


def test_autopsy_async_equals_session_collect() -> None:
    cfg = config(max_attempts=1)

    async def via_session() -> BatchResult:
        async with sources.SourceSession(
            cfg, transport=httpx.MockTransport(Web(left_pad_routes())), clock=FakeClock()
        ) as s:
            return await s.collect(REQUESTS)

    async def via_api() -> BatchResult:
        return await sources.autopsy_async(
            REQUESTS,
            config=cfg,
            transport=httpx.MockTransport(Web(left_pad_routes())),
            clock=FakeClock(),
        )

    expected = asyncio.run(via_session())
    actual = asyncio.run(via_api())
    assert actual == expected
    assert actual.results[0].signals is not None


def test_autopsy_equals_asyncio_run_of_autopsy_async() -> None:
    cfg = config(max_attempts=1)
    sync = sources.autopsy(REQUESTS, **_kwargs(cfg))
    run = asyncio.run(sources.autopsy_async(REQUESTS, **_kwargs(cfg)))
    assert sync == run
    assert sync.results[0].signals is not None


@pytest.mark.filterwarnings("ignore:coroutine .* was never awaited:RuntimeWarning")
def test_autopsy_inside_a_running_loop_raises_runtime_error() -> None:
    cfg = config(max_attempts=1)

    async def main() -> None:
        sources.autopsy(REQUESTS, **_kwargs(cfg))

    with pytest.raises(RuntimeError):
        asyncio.run(main())
    gc.collect()  # the never-awaited coroutine warns here, under the filter, not in a later test


# ------------------------------------------------------------------ T10.5 additions


def _mixed_requests(seed: int) -> list[tuple[Any, Any]]:
    """Every generated input with invalid items (bad purl, versionless, datetime, non-str)."""
    valid = fakeweb(seed).inputs
    first = valid[0][0]
    invalid: list[tuple[Any, Any]] = [
        ("not a purl", AS_OF),
        (first.split("@")[0], AS_OF),
        (first, datetime(2026, 11, 3, tzinfo=UTC)),
        (42, AS_OF),
    ]
    return [*invalid[:2], *valid, *invalid[2:]]


def test_autopsy_with_invalid_items_equals_asyncio_run_of_autopsy_async() -> None:
    """SRC-TEST-16: the sync wrapper adds nothing, with per-item errors in the batch."""
    cfg = config(max_attempts=1)
    requests = _mixed_requests(2)

    def kwargs() -> dict[str, Any]:
        return {
            "config": cfg,
            "token": SecretToken(TOKEN_TEXT),
            "transport": fakeweb(2).transport,
            "clock": FakeClock(),
        }

    sync = sources.autopsy(requests, **kwargs())
    run = asyncio.run(sources.autopsy_async(requests, **kwargs()))
    assert sync == run
    assert [r.error is not None for r in sync.results] == [
        True,
        True,
        *[False] * len(fakeweb(2).inputs),
        True,
        True,
    ]
    check_batch(sync)


@pytest.mark.parametrize("use_sync", [True, False])
def test_too_many_packages_raises_value_error_and_sends_nothing(use_sync: bool) -> None:
    base = config(max_attempts=1)
    cfg = SourcesConfig(
        hosts=base.hosts,
        contact=base.contact,
        timeouts=base.timeouts,
        limits=Limits(max_packages_per_call=1),
    )
    web = Web(left_pad_routes())
    kwargs: dict[str, Any] = {
        "config": cfg,
        "transport": httpx.MockTransport(web),
        "clock": FakeClock(),
    }
    two = [(LEFT_PAD, AS_OF), ("pkg:npm/other@1.0.0", AS_OF)]
    with pytest.raises(ValueError, match="too many packages"):
        if use_sync:
            sources.autopsy(two, **kwargs)
        else:
            asyncio.run(sources.autopsy_async(two, **kwargs))
    assert web.urls == []


def test_the_token_given_to_autopsy_reaches_github_and_no_other_host() -> None:
    web = fakeweb(3)
    batch = sources.autopsy(
        web.inputs,
        config=config(max_attempts=1),
        token=SecretToken(TOKEN_TEXT),
        transport=web.transport,
        clock=FakeClock(),
    )
    assert web.counts.hosts["api.github.com"] >= 1
    assert web.leaked_auth == []
    assert "GITHUB_DISABLED" not in {w.code for r in batch.results for w in r.warnings}
    assert TOKEN_TEXT not in repr(batch)
