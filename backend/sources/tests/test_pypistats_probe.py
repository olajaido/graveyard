"""The default pypistats interval respects the recorded probe (T13.5; SRC-REC-5, SRC-S9-4).

``fixtures/recorded/pypistats_probe.json`` is written by ``scripts/record_source_responses.py
--probe-pypistats`` (maintainer-run, T12). It holds, per request, the pause before it, the
status, ``Retry-After`` and the ``x-ratelimit-*`` headers, and the computed
``safe_interval_seconds``: the smallest tested interval reached without a 429.

The default interval for ``pypistats.org`` must be at least twice that value (SRC-S9-4), so a
measurement the default does not respect cannot be forgotten. If the probe is absent, or found
no safe interval, the checks that need it are skipped with a message.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.sources.config import SourcesConfig

PROBE = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "sources"
    / "tests"
    / "fixtures"
    / "recorded"
    / "pypistats_probe.json"
)
HOST = "pypistats.org"
MARGIN = 2.0
"""SRC-S9-4: the default is at least this multiple of the measured safe interval."""


def _probe() -> dict[str, Any]:
    if not PROBE.is_file():
        pytest.skip(f"no probe recorded at {PROBE.name} (run T12 with --probe-pypistats)")
    data = json.loads(PROBE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _default_interval() -> float:
    return SourcesConfig.default(contact="ops@example.org").hosts[HOST].min_interval_seconds


def test_the_probe_has_the_documented_shape() -> None:
    probe = _probe()
    assert probe["host"] == HOST
    assert set(probe) == {
        "host",
        "recorded_on",
        "configured_interval_seconds",
        "stopped_at_429",
        "safe_interval_seconds",
        "requests",
    }
    assert 1 <= len(probe["requests"]) <= 12
    for request in probe["requests"]:
        assert set(request) == {
            "interval_seconds",
            "package",
            "status",
            "error",
            "retry_after",
            "ratelimit_headers",
        }


def test_the_probe_stored_no_secret_or_foreign_header() -> None:
    text = PROBE.read_text(encoding="utf-8") if PROBE.is_file() else ""
    if not text:
        pytest.skip("no probe recorded")
    lowered = text.lower()
    for forbidden in ("authorization", "bearer", "cookie", "ghp_", "github_pat_"):
        assert forbidden not in lowered
    for request in json.loads(text)["requests"]:
        for name in request["ratelimit_headers"]:
            assert name.startswith(("x-ratelimit-", "ratelimit-"))


def test_the_recorded_requests_were_sequential_and_stopped_at_a_429_if_there_was_one() -> None:
    probe = _probe()
    statuses = [r["status"] for r in probe["requests"]]
    if 429 in statuses:
        assert statuses[-1] == 429, "the probe must stop at the first 429"
        assert probe["stopped_at_429"] is True
    else:
        assert probe["stopped_at_429"] is False
        assert len(statuses) == 12


def test_the_safe_interval_is_the_last_group_reached_without_a_429() -> None:
    probe = _probe()
    groups: dict[float, list[int | None]] = {}
    for request in probe["requests"]:
        groups.setdefault(request["interval_seconds"], []).append(request["status"])
    expected: float | None = None
    for interval, statuses in groups.items():  # in the order they were sent
        if 429 in statuses:
            break
        expected = interval
    assert probe["safe_interval_seconds"] == expected


def test_the_default_interval_is_at_least_twice_the_measured_safe_interval() -> None:
    safe = _probe()["safe_interval_seconds"]
    if safe is None:
        pytest.skip("the probe found no safe interval; the default needs a decision, not a check")
    assert _default_interval() >= MARGIN * float(safe)


def test_the_default_interval_is_the_one_the_spec_states() -> None:
    # SRC-S9-4: 1.2 s, above twice the 0.5 s measured on 2026-11-11. Change this, the config
    # and the spec together.
    assert _default_interval() == 1.2


def test_the_recorded_configuration_is_history_not_the_current_default() -> None:
    # The probe records the interval configured when it ran (3.0 s). It is a fact about that
    # run; the current default is checked against `safe_interval_seconds`, not against it.
    probe = _probe()
    assert probe["configured_interval_seconds"] > 0
