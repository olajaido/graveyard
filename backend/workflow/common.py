"""What every task handler shares: the dependency bundle and the error wrapper.

``Deps`` holds everything with a side effect, so a handler body is a plain function of
``(event, deps)`` and tests pass fakes. ``runtime.py`` builds the real ``Deps``.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from core.scan.errors import INTERNAL, INVALID_INPUT, ScanError
from core.scan.ids import is_scan_id
from core.sources.secret import SecretToken
from exhume.github_app import installation_token
from scan.store import Artefacts, ScanTable

log = logging.getLogger("graveyard")

GITHUB_BASE_URL: Final = "https://api.github.com"


@dataclass
class Deps:
    table: ScanTable
    artefacts: Artefacts
    param: Callable[[str], str]  # one SSM parameter below /graveyard/<env>/
    secret: Callable[[], str]  # the reader app's PEM key; never cached by the caller
    github: Callable[[], httpx.Client]  # client with base_url https://api.github.com
    now: Callable[[], float]  # epoch seconds
    metric: Callable[..., None]  # metric(name, value, unit="Count", **dimensions)


def scan_id_of(event: dict[str, Any]) -> str:
    scan_id = event.get("scanId")
    if not isinstance(scan_id, str) or not is_scan_id(scan_id):
        raise INVALID_INPUT
    return scan_id


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_stage(deps: Deps, scan_id: str, stage: str, **extra: Any) -> None:
    deps.table.update_scan(scan_id, stage=stage, updatedAt=iso(deps.now()), **extra)


def reader_token(deps: Deps) -> SecretToken:
    """A fresh installation token of the Reader app (SB-FET-1). The key is read per call."""
    client = deps.github()
    try:
        return installation_token(
            client,
            deps.param("github/reader/app-id"),
            deps.param("github/reader/installation-id"),
            deps.secret(),
            int(deps.now()),
        )
    finally:
        client.close()


def task[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Turn any non-``ScanError`` into ``INTERNAL`` so the state machine sees a fixed name."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except ScanError:
            raise
        except Exception as exc:
            # Only the class name is logged: a message or traceback could carry a token or a body.
            log.error("task failed: %s", type(exc).__name__)
            raise INTERNAL from None

    return wrapper
