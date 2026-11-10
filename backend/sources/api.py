"""Public entry points of the I/O half: ``autopsy_async`` and ``autopsy`` (SRC-API-1, D2).

``autopsy_async`` opens a ``SourceSession``, collects the batch and closes the session.
``autopsy`` is ``asyncio.run(autopsy_async(...))`` and nothing else. Callers that want to
share limiters and cache across several calls use ``SourceSession`` directly.

D3, never raise: source, network and data problems never raise; they become per-item errors
and warnings in the ``BatchResult``. ``ValueError`` is for programmer errors only (for
example, more requests than ``Limits.max_packages_per_call``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date

import httpx

from core.sources.clock import Clock
from core.sources.config import SourcesConfig
from core.sources.model import BatchResult
from core.sources.secret import SecretToken
from sources.cache import SourceCache
from sources.session import SourceSession


async def autopsy_async(
    requests: Sequence[tuple[str, date]],
    *,
    config: SourcesConfig,
    token: SecretToken | None = None,
    cache: SourceCache | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Clock | None = None,
) -> BatchResult:
    """Analyse ``requests`` (purl text, ``as_of``) and return one result per input, in order."""
    async with SourceSession(
        config, token=token, cache=cache, transport=transport, clock=clock
    ) as session:
        return await session.collect(requests)


def autopsy(
    requests: Sequence[tuple[str, date]],
    *,
    config: SourcesConfig,
    token: SecretToken | None = None,
    cache: SourceCache | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Clock | None = None,
) -> BatchResult:
    """Synchronous ``autopsy_async``.

    Inside a running event loop ``asyncio.run`` raises ``RuntimeError``; use
    ``autopsy_async`` there.
    """
    return asyncio.run(
        autopsy_async(
            requests,
            config=config,
            token=token,
            cache=cache,
            transport=transport,
            clock=clock,
        )
    )


__all__ = ["autopsy", "autopsy_async"]
