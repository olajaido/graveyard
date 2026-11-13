"""Property tests for ``eval.fixture`` (EV-NOGH-2, EV-RUN-3)."""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.sources.assemble import FEEDS
from eval.fixture import (
    LoadedFixture,
    load_fixtures,
    no_github_variant,
    signals_from_fixture,
    warnings_from_fixture,
)
from eval.tests.support import anchor_copy, s1_parts, write_fixture_set

pytestmark = pytest.mark.property

ANCHOR_NAMES = [
    "express",
    "left-pad",
    "moment",
    "node-uuid",
    "nose",
    "pycrypto",
    "request",
    "six",
    "uuid",
]

# The Signals fields fed by GitHub; the variant nulls these (S1 is handled separately).
GITHUB_FIELDS = ("s3_last_push_at", "s5_committers", "s6_open_issues", "s6_closed_issues")
SKIPPED = {*GITHUB_FIELDS, "s1_declared_death"}


def _entry(value: Any, source: str, unavailable: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {"value": value, "source": source, "fetched_at": "2026-11-08T00:00:00Z"}
    if unavailable:
        entry["unavailable"] = True
    return entry


_DAYS = st.dates().map(lambda d: d.isoformat())
_COUNT = st.none() | st.integers(0, 10_000)
_GH = "https://api.github.com/graphql"


@st.composite
def fixtures(draw: st.DrawFn) -> tuple[dict[str, Any], bool | None]:
    """A valid fixture dict (anchor base, varied scored signals) and its registry flag."""
    raw = anchor_copy(draw(st.sampled_from(ANCHOR_NAMES)))
    if draw(st.booleans()):
        raw["repo"] = None
    signals = raw["signals"]
    signals["s3_last_push_at"] = _entry(draw(st.none() | _DAYS), _GH, draw(st.booleans()))
    signals["s5_committers"] = _entry(draw(_COUNT), _GH, draw(st.booleans()))
    signals["s6_open_issues"] = _entry(draw(_COUNT), _GH, draw(st.booleans()))
    signals["s6_closed_issues"] = _entry(draw(_COUNT), _GH, draw(st.booleans()))
    signals["s1_declared_death"] = _entry(draw(st.none() | st.booleans()), _GH, False)
    signals["s2_latest_release_at"] = _entry(
        draw(st.none() | _DAYS), "https://registry.npmjs.org/pkg", draw(st.booleans())
    )
    signals["s8_overall"] = _entry(
        draw(st.none() | st.floats(0.0, 10.0)), "https://api.securityscorecards.dev/", False
    )
    registry = draw(st.none() | st.booleans())
    raw["s1_parts"] = s1_parts(registry=registry, archived=draw(st.none() | st.booleans()))
    return raw, registry


def _loaded(raw: Mapping[str, Any], registry: bool | None) -> LoadedFixture:
    signals = signals_from_fixture(raw)
    return LoadedFixture(
        ecosystem=raw["ecosystem"],
        package=raw["package"],
        resolved_version=raw["resolved_version"],
        as_of=signals.as_of,
        signals=signals,
        warnings=warnings_from_fixture(raw),
        registry_deprecated=registry,
        raw=raw,
    )


@given(case=fixtures())
def test_no_github_variant_never_adds_information(case: tuple[dict[str, Any], bool | None]) -> None:
    """**Validates: Requirements EV-NOGH-2, EV-NOGH-5**"""
    raw, registry = case
    loaded = _loaded(raw, registry)
    signals, warnings = no_github_variant(loaded)

    for name in GITHUB_FIELDS:
        assert getattr(signals, name) is None
    for f in fields(signals):
        if f.name not in SKIPPED:
            assert getattr(signals, f.name) == getattr(loaded.signals, f.name)
    assert signals.s1_declared_death in (None, True)
    if signals.s1_declared_death is True:
        assert registry is True

    disabled = [w for w in warnings if w.code == "GITHUB_DISABLED"]
    if raw["repo"] is None:
        assert disabled == []
    else:
        assert len(disabled) == 1
        assert disabled[0].source == "github"
        assert set(disabled[0].signals) == set(FEEDS["github"])
        assert warnings[-1] is disabled[0]


@given(
    names=st.lists(st.sampled_from(ANCHOR_NAMES), min_size=1, max_size=9, unique=True),
    data=st.data(),
)
def test_load_order_independent(names: list[str], data: st.DataObject) -> None:
    """**Validates: Requirements EV-RUN-3**"""
    entries = [{"fixture": anchor_copy(n)} for n in names]
    keys = [(e["fixture"]["ecosystem"], e["fixture"]["package"]) for e in entries]
    shuffled = data.draw(st.permutations(keys))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_fixture_set(root, entries)
        first = load_fixtures(root, keys)
        second = load_fixtures(root, shuffled)
    assert list(first.items()) == list(second.items())
