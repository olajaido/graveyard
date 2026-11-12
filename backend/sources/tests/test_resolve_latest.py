"""``SourceSession.resolve_latest`` over the recorded cassette (KPW-RES-1…6).

Replay only: no network, no real clock. Every run that should stay inside the cassette
asserts ``log.unmatched == []``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Final

import httpx
import pytest

from core.sources.config import SourcesConfig
from core.sources.model import LatestResult
from core.sources.tests import recorded as rec
from sources.session import SourceSession
from sources.tests.clock import FakeClock
from sources.tests.transports import ReplayLog, replay_transport

_START: Final = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
_EXPRESS: Final = "pkg:npm/express"
_REQUEST: Final = "pkg:npm/request"
_SIX: Final = "pkg:pypi/six"

Wrap = Callable[
    [Callable[[httpx.Request], httpx.Response]], Callable[[httpx.Request], httpx.Response]
]


def _resolve(
    purls: Sequence[str], wrap: Wrap | None = None
) -> tuple[dict[str, LatestResult], ReplayLog, list[str]]:
    """Resolve over the cassette; ``wrap`` may replace the handler. Returns the URLs sent."""
    inner, log = replay_transport(rec.cassette())
    sent: list[str] = []
    handler = inner.handler

    def recording(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return handler(request)  # type: ignore[return-value]

    final = wrap(recording) if wrap is not None else recording

    async def go() -> dict[str, LatestResult]:
        async with SourceSession(
            SourcesConfig.default(contact="ops@example.org"),
            transport=httpx.MockTransport(final),
            clock=FakeClock(_START),
        ) as session:
            return dict(await session.resolve_latest(purls))

    return asyncio.run(go()), log, sent


def test_cassette_latest_versions() -> None:
    results, log, _ = _resolve([_EXPRESS, _REQUEST, _SIX])
    assert {p: (r.version, r.via) for p, r in results.items()} == {
        _EXPRESS: ("5.3.0", "registry"),
        _REQUEST: ("2.88.2", "registry"),
        _SIX: ("1.17.0", "registry"),
    }
    assert all(r.error is None for r in results.values())
    assert log.unmatched == []


def test_express_is_the_dist_tag_not_latest_4() -> None:
    results, _, _ = _resolve([_EXPRESS])
    assert results[_EXPRESS].version != "4.22.3"


def test_input_order_and_duplicates() -> None:
    results, log, sent = _resolve([_SIX, _EXPRESS, _SIX, _REQUEST])
    assert list(results) == [_SIX, _EXPRESS, _REQUEST]
    assert sent.count("https://pypi.org/pypi/six/json") == 1
    assert log.unmatched == []


def test_registry_404_is_an_error_and_never_asks_depsdev() -> None:
    def wrap(inner: Callable[[httpx.Request], httpx.Response]) -> Callable[..., httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "pypi.org":
                return httpx.Response(404, json={"message": "Not Found"})
            return inner(request)

        return handler

    results, _, sent = _resolve([_SIX], wrap)
    assert results[_SIX].version is None
    assert results[_SIX].via is None
    assert results[_SIX].error is not None
    assert not any("deps.dev" in url for url in sent)


def test_registry_failure_falls_back_to_the_depsdev_default() -> None:
    def wrap(inner: Callable[[httpx.Request], httpx.Response]) -> Callable[..., httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "pypi.org":
                raise httpx.ConnectError("down", request=request)
            return inner(request)

        return handler

    results, log, sent = _resolve([_SIX], wrap)
    assert results[_SIX].via == "depsdev"
    assert results[_SIX].version == "1.17.0"
    assert results[_SIX].error is None
    assert any("deps.dev" in url for url in sent)
    assert log.unmatched == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not a purl",
        "pkg:npm/express@4.18.2",
        "pkg:pypi/six@1.17.0",
        "pkg:maven/a/b",
        "pkg:cargo/x",
    ],
)
def test_bad_inputs_are_value_errors_before_any_request(text: str) -> None:
    with pytest.raises(ValueError):
        _resolve([_EXPRESS, text])


def test_bad_input_sends_nothing() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(500)

    async def go() -> None:
        async with SourceSession(
            SourcesConfig.default(contact="ops@example.org"),
            transport=httpx.MockTransport(handler),
            clock=FakeClock(_START),
        ) as session:
            await session.resolve_latest([_EXPRESS, "pkg:npm/express@1.0.0"])

    with pytest.raises(ValueError):
        asyncio.run(go())
    assert sent == []
