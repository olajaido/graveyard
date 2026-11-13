"""Test support for the ``mcp_server`` suite (T11.3; KPW-TEST-12).

* ``cassette_transport`` replays the recorded cassette (single-package requests included) and
  keeps the headers of every request, so a test can see whether a token was sent.
* ``call_tool`` and ``list_tools`` use the SDK's in-memory client/server pairing: no
  subprocess, no socket.
* ``use_stub_syft`` puts the stub Syft first on ``PATH`` for one test (``autopsy_project`` has
  no ``--syft`` argument, so the pipeline finds Syft on ``PATH``).

Not part of the wheel (it lives under ``tests/``). No network.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import anyio
import httpx
import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, ListToolsResult, TextContent

from cli.env import CliEnvironment
from cli.tests.support import (
    FakeClock,
    StubSyft,
    make_env,
    make_stub_syft,
    single_repo_github,
    subset_replay_transport,
)
from core.sources.secret import SecretToken
from core.sources.tests import recorded as rec
from sources.tests.transports import ReplayLog

__all__ = [
    "ANCHORS_PROJECT",
    "CLOCK_START",
    "FIXTURES_ROOT",
    "EXPRESS_PURL",
    "REQUEST_PURL",
    "TOKEN",
    "CapturedTransport",
    "OverlapProbe",
    "all_text",
    "call_tool",
    "cassette_transport",
    "first_text",
    "fresh_clock",
    "list_tools",
    "make_token_env",
    "use_stub_syft",
]

FIXTURES_ROOT: Final = Path(__file__).resolve().parents[2] / "cli" / "tests" / "fixtures"
ANCHORS_PROJECT: Final = FIXTURES_ROOT / "anchors-project"
REQUEST_PURL: Final = "pkg:npm/request@2.88.2"
EXPRESS_PURL: Final = "pkg:npm/express@4.17.1"
# A distinctive token: any appearance of it in a result, error or repr is a leak.
TOKEN: Final = "ghp_MCPtestDistinctiveSecret0123456789"
CLOCK_START: Final = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def fresh_clock() -> FakeClock:
    """A fake clock on the cassette's ``as_of`` day."""
    return FakeClock(CLOCK_START)


def make_token_env(token: str | None = TOKEN) -> CliEnvironment:
    """A ``CliEnvironment`` holding ``token`` (or none)."""
    return make_env(token=SecretToken(token) if token is not None else None)


@dataclass
class CapturedTransport:
    """A replay transport plus what it saw."""

    transport: httpx.MockTransport
    log: ReplayLog
    headers: list[httpx.Headers] = field(default_factory=list)

    @property
    def authorization_sent(self) -> bool:
        return any("authorization" in h for h in self.headers)


def cassette_transport() -> CapturedTransport:
    """Replay the cassette: every request the tools can make for the two recorded packages.

    A single-package OSV or downloads request is derived from the recorded batch answers and
    a one-repository GitHub query from the recorded batch (``cli.tests.support``).
    """
    cassette = rec.cassette()
    inner, log = subset_replay_transport(cassette)
    github = single_repo_github(inner, log, cassette)
    captured = CapturedTransport(transport=inner, log=log)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.headers.append(request.headers)
        answer = github.handler(request)
        assert isinstance(answer, httpx.Response)  # the replay handlers are synchronous
        return answer

    captured.transport = httpx.MockTransport(handler)
    return captured


async def _call(server: MCPServer, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async with Client(server) as client:
        return await client.call_tool(name, arguments)


async def _list(server: MCPServer) -> ListToolsResult:
    async with Client(server) as client:
        return await client.list_tools()


def call_tool(server: MCPServer, name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Call one tool through the in-memory client/server pair."""
    return anyio.run(_call, server, name, arguments)


def list_tools(server: MCPServer) -> ListToolsResult:
    """List the tools through the in-memory client/server pair."""
    return anyio.run(_list, server)


def first_text(result: CallToolResult) -> str:
    """The text of the result's only content block."""
    assert len(result.content) == 1
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


def all_text(result: CallToolResult) -> str:
    """Everything a client could read in ``result``: the text blocks and the structured part."""
    parts = [repr(result.structured_content)]
    parts.extend(str(getattr(block, "text", block)) for block in result.content)
    return "\n".join(parts)


def use_stub_syft(monkeypatch: pytest.MonkeyPatch, work: Path) -> StubSyft:
    """Write the stub Syft into ``work/bin`` and put that directory first on ``PATH``."""
    bin_dir = work / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = make_stub_syft(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return stub


class OverlapProbe:
    """Counts how many wrapped calls run at the same time.

    ``wrap(fn)`` returns a function that delegates to ``fn`` after a short pause (long enough
    for a second thread to start) and records the highest number of calls inside at once.
    """

    def __init__(self, pause: float = 0.05) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self._pause = pause
        self.max_active = 0
        self.calls = 0
        self.threads: set[int] = set()  # ids of the threads the wrapped calls ran in

    def wrap(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                self._active += 1
                self.calls += 1
                self.threads.add(threading.get_ident())
                self.max_active = max(self.max_active, self._active)
            try:
                time.sleep(self._pause)
                return fn(*args, **kwargs)
            finally:
                with self._lock:
                    self._active -= 1

        return wrapper
