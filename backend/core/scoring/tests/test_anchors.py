"""Fixture-driven real-data anchors (MM-ANC-1..9). No network; fixtures are committed."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from core.scoring import score_package
from core.scoring.types import Advisory, BaseState, PathInfo, ScoringResult, Signals
from core.scoring.weights import load_weights

FIXTURES = Path(__file__).parent / "fixtures" / "anchors"


def _date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def signals_from_fixture(fixture: dict[str, Any]) -> Signals:
    """Map a captured fixture to Signals (dates parsed; lists become tuples; None stays None)."""
    s = fixture["signals"]

    def v(key: str) -> Any:
        return s[key]["value"]

    raw_adv = v("s7_advisories")
    advisories = (
        None
        if raw_adv is None
        else tuple(
            Advisory(id=a["id"], has_fix=a["has_fix"], published_at=_date(a["published_at"]))
            for a in raw_adv
        )
    )
    raw_paths = fixture.get("paths")
    paths = (
        None
        if raw_paths is None
        else tuple(PathInfo(runtime=p["runtime"], direct=p["direct"]) for p in raw_paths)
    )
    return Signals(
        purl=fixture["purl"],
        as_of=date.fromisoformat(fixture["as_of"]),
        s2_latest_release_at=_date(v("s2_latest_release_at")),
        s3_last_push_at=_date(v("s3_last_push_at")),
        s4_maintained=v("s4_maintained"),
        s5_committers=v("s5_committers"),
        s6_open_issues=v("s6_open_issues"),
        s6_closed_issues=v("s6_closed_issues"),
        s8_overall=v("s8_overall"),
        s1_declared_death=v("s1_declared_death"),
        s1b_version_deprecated=v("s1b_version_deprecated"),
        s7_advisories=advisories,
        s9_weekly_downloads=v("s9_weekly_downloads"),
        paths=paths,
        services_affected=fixture.get("services_affected"),
        shared_repo=fixture.get("shared_repo", False),
    )


def _load(name: str) -> tuple[dict[str, Any], ScoringResult]:
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return fixture, score_package(signals_from_fixture(fixture))


def _check_common(
    result: ScoringResult,
    state: BaseState,
    reason: str | None,
    cursed: bool,
    wounded: bool,
) -> None:
    assert result.base_state == state
    assert result.dead_reason == reason
    assert result.cursed is cursed
    assert result.wounded is wounded
    # paths are null in every fixture
    assert result.exposure == 1.0
    assert result.exposure_assumed is True


def test_anchor_request() -> None:
    fixture, r = _load("request")
    _check_common(r, BaseState.DEAD, "declared", cursed=True, wounded=False)
    adv = fixture["signals"]["s7_advisories"]["value"]
    assert len(adv) == 1 and adv[0]["has_fix"] is False


def test_anchor_node_uuid() -> None:
    _, r = _load("node-uuid")
    _check_common(r, BaseState.DEAD, "declared", cursed=False, wounded=False)


def test_anchor_left_pad() -> None:
    _, r = _load("left-pad")
    _check_common(r, BaseState.DEAD, "declared", cursed=False, wounded=False)
    assert r.mortality == load_weights().threshold_s1_min_score


def test_anchor_express() -> None:
    fixture, r = _load("express")
    _check_common(r, BaseState.ALIVE, None, cursed=False, wounded=True)
    assert fixture["signals"]["s1b_version_deprecated"]["value"] is False
    assert len(fixture["signals"]["s7_advisories"]["value"]) == 2


def test_anchor_uuid() -> None:
    fixture, r = _load("uuid")
    _check_common(r, BaseState.ALIVE, None, cursed=False, wounded=True)
    assert fixture["signals"]["s1b_version_deprecated"]["value"] is True


def test_anchor_moment() -> None:
    fixture, r = _load("moment")
    _check_common(r, BaseState.ALIVE, None, cursed=False, wounded=True)
    assert len(fixture["signals"]["s7_advisories"]["value"]) == 2


def _expected_s2_only_confidence() -> float:
    w = load_weights().weights
    return w["s2"] / sum(w.values())


def test_anchor_pycrypto() -> None:
    fixture, r = _load("pycrypto")
    _check_common(r, BaseState.DEAD, "score", cursed=True, wounded=False)
    assert r.confidence == pytest.approx(0.25)
    assert r.confidence == pytest.approx(_expected_s2_only_confidence())
    adv = fixture["signals"]["s7_advisories"]["value"]
    assert len(adv) == 4 and not any(a["has_fix"] for a in adv)


def test_anchor_nose() -> None:
    _, r = _load("nose")
    _check_common(r, BaseState.DEAD, "score", cursed=False, wounded=False)
    assert r.confidence == pytest.approx(0.25)
    assert r.confidence == pytest.approx(_expected_s2_only_confidence())


def test_anchor_six_borderline_sentinel() -> None:
    _, r = _load("six")
    w = load_weights()
    _check_common(r, BaseState.RESTING, None, cursed=False, wounded=False)
    assert r.mortality is not None
    assert w.threshold_ailing <= r.mortality < w.threshold_dead
    # Borderline sentinel: ~43.7 today; drift beyond 0.5 signals a model or fixture change.
    assert r.mortality == pytest.approx(43.7, abs=0.5)
