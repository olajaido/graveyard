"""Shared set-up for the ``test_clients_*.py`` files (T9.5).

``run_clients`` builds one ``HttpGateway`` on ``httpx.MockTransport`` and ``FakeClock``, one
``CacheContext`` over a ``MemoryCache``, and runs a scenario with the resulting
``ClientContext`` inside ``asyncio.run`` (no ``pytest-asyncio``). Every request that reaches the
transport is recorded in ``Run.sent`` (method, URL as sent, parsed JSON body, ``Accept``), so a
test can compare it with the ``core.sources.urls`` builder output. Nothing touches the network.

Helpers for hand-built bodies: ``ok`` (a handler step answering with JSON), ``script`` (a handler
that plays steps in order), and ``body_of`` (the JSON body of a request).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final

import httpx

from core.sources.config import CachePolicy, RetryPolicy, SourcesConfig, Timeouts
from sources.cache import CacheContext, MemoryCache
from sources.clients.common import ClientContext
from sources.gateway import HttpGateway
from sources.tests.clock import FakeClock
from sources.tests.transports import CountingHandler, Handler, counting_handler, json_response

CONTACT: Final = "ops@example.org"
JSON: Final = "application/json"

type Step = Callable[[httpx.Request], httpx.Response]


@dataclass(frozen=True)
class Sent:
    """One request that reached the transport."""

    method: str
    url: str
    body: object
    accept: str


@dataclass
class Run[T]:
    """What a scenario returned and what the transport saw."""

    value: T
    clock: FakeClock
    cache: CacheContext
    seen: CountingHandler
    sent: list[Sent] = field(default_factory=list)

    @property
    def urls(self) -> list[str]:
        return [s.url for s in self.sent]


def body_of(request: httpx.Request) -> dict[str, object]:
    """The JSON object a request carried."""
    loaded = json.loads(request.content)
    assert isinstance(loaded, dict)
    return loaded


def ok(data: object, status: int = 200) -> Step:
    """A step answering every request with ``data`` as JSON."""
    return lambda _request: json_response(data, status)


def script(*steps: Step) -> Callable[[httpx.Request], httpx.Response]:
    """A handler that plays ``steps`` in order and repeats the last one."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        step = steps[min(calls, len(steps) - 1)]
        calls += 1
        return step(request)

    return handler


def config(*, max_attempts: int = 4) -> SourcesConfig:
    """The default config; ``max_attempts=1`` makes a retryable status fail at once."""
    return SourcesConfig(
        hosts=SourcesConfig.default(contact=CONTACT).hosts,
        contact=CONTACT,
        # A long batch deadline, so a test may move the clock by days to expire cache entries.
        timeouts=Timeouts(batch_deadline=10_000_000.0),
        retry=RetryPolicy(max_attempts=max_attempts),
    )


def run_clients[T](
    handler: Handler,
    scenario: Callable[[ClientContext], Awaitable[T]],
    *,
    clock: FakeClock | None = None,
    max_attempts: int = 4,
) -> Run[T]:
    """Run ``scenario`` against ``handler`` through a real gateway and an in-memory cache."""
    clock = clock or FakeClock()
    sent: list[Sent] = []

    async def recording(request: httpx.Request) -> httpx.Response:
        content = request.content
        sent.append(
            Sent(
                request.method,
                str(request.url),
                json.loads(content) if content else None,
                request.headers.get("accept", ""),
            )
        )
        result = handler(request)
        if isinstance(result, httpx.Response):
            return result
        return await result

    seen = counting_handler(recording)
    gateway = HttpGateway(
        config(max_attempts=max_attempts),
        clock,
        transport=httpx.MockTransport(seen),
    )
    cache = CacheContext(MemoryCache(clock))

    async def main() -> T:
        async with gateway:
            return await scenario(ClientContext(gateway, cache, CachePolicy()))

    value = asyncio.run(main())
    return Run(value, clock, cache, seen, sent)
