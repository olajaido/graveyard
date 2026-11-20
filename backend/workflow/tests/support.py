"""Fakes and builders for the handler tests."""

from __future__ import annotations

from typing import Any

import httpx

from core.scan.ids import new_scan_id
from exhume.tests.support import make_key
from scan.fakes import FakeArtefacts, FakeTable
from workflow.common import Deps

PRIVATE_PEM, _PUBLIC = make_key()
SCAN_ID = new_scan_id(1_763_000_000_000, bytes(range(10)), bytes(range(8)))
NOW = 1_763_000_000.0
PARAMS = {
    "kill-switch": "false",
    "limits/max-services": "50",
    "limits/max-manifest-bytes": "10485760",
    "limits/max-file-bytes": "5242880",
    "limits/max-purls": "2000",
    "sources/contact": "ops@example.org",
    "github/reader/app-id": "12345",
    "github/reader/installation-id": "678",
}


class Recorder:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict[str, str]]] = []

    def __call__(self, name: str, value: float, unit: str = "Count", **dimensions: str) -> None:
        self.metrics.append((name, value, dimensions))


def make_deps(
    github: httpx.MockTransport | None = None,
    params: dict[str, str] | None = None,
    table: FakeTable | None = None,
    artefacts: FakeArtefacts | None = None,
) -> tuple[Deps, FakeTable, FakeArtefacts, Recorder]:
    table = table or FakeTable()
    artefacts = artefacts or FakeArtefacts()
    recorder = Recorder()
    merged = {**PARAMS, **(params or {})}
    transport = github or httpx.MockTransport(lambda r: httpx.Response(500))
    deps = Deps(
        table=table,
        artefacts=artefacts,
        param=merged.__getitem__,
        secret=lambda: PRIVATE_PEM,
        github=lambda: httpx.Client(transport=transport, base_url="https://api.github.com"),
        now=lambda: NOW,
        metric=recorder,
    )
    return deps, table, artefacts, recorder


def queued_scan(table: FakeTable, repo: str = "olajaido/haunted-house") -> dict[str, Any]:
    meta: dict[str, Any] = {
        "scanId": SCAN_ID,
        "source": {"type": "github", "repo": repo},
        "status": "QUEUED",
        "stage": "QUEUED",
        "createdAt": "2025-11-12T22:13:20Z",
    }
    table.create_scan(SCAN_ID, meta)
    return meta
