"""Budget tests for ``check-install`` (T9.4; KPW-BUD-1…3).

A transport whose handler never answers stands in for a dead network. Everything else is
answered from the recorded cassette (``request@2.88.2`` is declared Dead and gate-eligible).
"""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from cli.app import run
from cli.tests.support import FakeClock, make_env, subset_replay_transport
from cli.tests.test_e2e_project import CLOCK_START
from core.sources.tests import recorded as rec

SILENT = "zzz-never-answers"


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str
    seconds: float


def _transport(is_silent: Callable[[httpx.Request], bool]) -> httpx.MockTransport:
    """Replay the cassette, except that requests picked by ``is_silent`` never get an answer."""
    inner, _ = subset_replay_transport(rec.cassette())

    async def handler(request: httpx.Request) -> httpx.Response:
        if is_silent(request):
            await asyncio.sleep(3600)
        return inner.handler(request)  # type: ignore[return-value]

    return httpx.MockTransport(handler)


def _mentions_silent(request: httpx.Request) -> bool:
    return SILENT in str(request.url) or SILENT.encode() in request.content


def _check(command: str, transport: httpx.MockTransport, budget: str = "0.5") -> Result:
    out, err = io.StringIO(), io.StringIO()
    started = time.monotonic()
    code = run(
        ["check-install", command, "--budget", budget, "--as-of", "2026-11-03"],
        env=make_env(),
        out=out,
        err=err,
        transport=transport,
        clock=FakeClock(CLOCK_START),
    )
    return Result(code, out.getvalue(), err.getvalue(), time.monotonic() - started)


def test_never_answering_transport_times_out_with_exit_0() -> None:
    result = _check("npm install request@2.88.2", _transport(lambda _r: True))
    assert result.code == 0
    assert "check timed out after 0.5s (1 package not checked)" in result.out
    assert result.err == ""
    assert result.seconds < 3


def test_answered_dead_package_blocks_and_silent_one_is_not_named() -> None:
    result = _check(f"npm install request@2.88.2 {SILENT}@1.0.0", _transport(_mentions_silent))
    assert result.code == 2
    assert "request" in result.err
    assert SILENT not in result.err
    assert result.out == ""
    assert result.seconds < 3


def test_resolution_timeout_leaves_pinned_targets_checked() -> None:
    result = _check(f"npm install request@2.88.2 {SILENT}", _transport(_mentions_silent))
    assert result.code == 2
    assert "request" in result.err
    assert SILENT not in result.err
    assert result.seconds < 3
