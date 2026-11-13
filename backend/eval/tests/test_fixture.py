"""Unit tests for ``eval.fixture`` (EV-RUN-3, EV-NOGH-1, EV-NOGH-2, EV-NOGH-5, EV-TEST-4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cli.gate import unverified_sources
from core.scoring import score_package
from core.scoring.tests import test_anchors
from core.scoring.types import BaseState
from core.sources.assemble import FEEDS
from eval import fixture as fx
from eval.fixture import FixtureError, LoadedFixture, load_fixtures, no_github_variant
from eval.tests.support import ANCHORS_DIR, anchor_copy, s1_parts, write_fixture_set

ANCHOR_NAMES = (
    "express",
    "left-pad",
    "moment",
    "node-uuid",
    "nose",
    "pycrypto",
    "request",
    "six",
    "uuid",
)
GITHUB_URL = "https://api.github.com/graphql"
GITHUB_SIGNALS = ("s3_last_push_at", "s5_committers", "s6_open_issues", "s6_closed_issues")


def _null(source: str | None = GITHUB_URL, *, unavailable: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {"value": None, "source": source, "fetched_at": "2026-11-03T10:00:00Z"}
    if unavailable:
        entry["unavailable"] = True
    return entry


def _github_nulled(name: str, *, unavailable: bool) -> dict[str, Any]:
    return anchor_copy(name, **{key: _null(unavailable=unavailable) for key in GITHUB_SIGNALS})


def _loaded(
    raw: dict[str, Any],
    *,
    registry: bool | None = None,
    archived: bool | None = None,
) -> LoadedFixture:
    raw["s1_parts"] = s1_parts(registry, archived)
    signals = fx.signals_from_fixture(raw)
    return LoadedFixture(
        ecosystem=raw["ecosystem"],
        package=raw["package"],
        resolved_version=raw["resolved_version"],
        as_of=signals.as_of,
        signals=signals,
        warnings=fx.warnings_from_fixture(raw),
        registry_deprecated=registry,
        raw=raw,
    )


# --- drift ---------------------------------------------------------------------------------


def test_anchor_list_is_complete() -> None:
    assert sorted(p.stem for p in ANCHORS_DIR.glob("*.json")) == sorted(ANCHOR_NAMES)


@pytest.mark.parametrize("name", ANCHOR_NAMES)
def test_signals_match_the_scoring_anchor_mapping(name: str) -> None:
    raw = anchor_copy(name)
    assert fx.signals_from_fixture(raw) == test_anchors.signals_from_fixture(raw)


# --- warnings ------------------------------------------------------------------------------


def test_unavailable_scored_signal_gives_one_warning() -> None:
    raw = anchor_copy("six", s3_last_push_at=_null(unavailable=True))
    warnings = fx.warnings_from_fixture(raw)
    assert len(warnings) == 1
    assert warnings[0].code == "INTERNAL_ERROR"
    assert warnings[0].source == "github"
    assert warnings[0].signals == ("s3_last_push_at",)


def test_two_failing_github_signals_share_one_warning() -> None:
    raw = anchor_copy(
        "six",
        s5_committers=_null(unavailable=True),
        s3_last_push_at=_null(unavailable=True),
    )
    warnings = fx.warnings_from_fixture(raw)
    assert len(warnings) == 1
    assert warnings[0].signals == ("s3_last_push_at", "s5_committers")


def test_null_signal_without_marker_gives_no_warning() -> None:
    assert fx.warnings_from_fixture(anchor_copy("six", s3_last_push_at=_null())) == ()


def test_marker_on_a_non_scored_signal_is_ignored() -> None:
    raw = anchor_copy("six")
    raw["signals"]["s9_weekly_downloads"]["unavailable"] = True
    raw["signals"]["s7_advisories"]["unavailable"] = True
    assert fx.warnings_from_fixture(raw) == ()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://api.github.com/graphql", "github"),
        ("https://api.deps.dev/v3/systems/npm/packages/x", "depsdev"),
        ("https://api.securityscorecards.dev/projects/github.com/a/b", "scorecard"),
        ("https://registry.npmjs.org/x", "npm_registry"),
        ("https://pypi.org/pypi/x/json", "pypi"),
        ("https://example.org/anything", "internal"),
        ("http://api.github.com/graphql", "internal"),
        (None, "internal"),
    ],
)
def test_host_maps_to_source_name(source: str | None, expected: str) -> None:
    raw = anchor_copy("six", s2_latest_release_at=_null(source, unavailable=True))
    warnings = fx.warnings_from_fixture(raw)
    assert [(w.source, w.signals) for w in warnings] == [(expected, ("s2_latest_release_at",))]


# --- unverified through the CLI function ---------------------------------------------------


def test_six_with_failed_github_is_dead_by_score_and_unverified() -> None:
    raw = _github_nulled("six", unavailable=True)
    signals = fx.signals_from_fixture(raw)
    result = score_package(signals)
    assert result.base_state is BaseState.DEAD
    assert result.dead_reason == "score"
    assert unverified_sources(result, signals, fx.warnings_from_fixture(raw)) == ("github",)


def test_six_with_nulls_but_no_marker_is_verified() -> None:
    raw = _github_nulled("six", unavailable=False)
    signals = fx.signals_from_fixture(raw)
    result = score_package(signals)
    assert unverified_sources(result, signals, fx.warnings_from_fixture(raw)) == ()


def test_nose_without_repo_is_verified() -> None:
    raw = anchor_copy("nose")
    signals = fx.signals_from_fixture(raw)
    result = score_package(signals)
    assert result.dead_reason == "score"
    assert unverified_sources(result, signals, fx.warnings_from_fixture(raw)) == ()


# --- without-GitHub derivation (EV-NOGH-2, EV-NOGH-5) --------------------------------------


def test_github_feed_keys_are_pinned() -> None:
    assert set(FEEDS["github"]) == {
        "s1_declared_death",
        "s3_last_push_at",
        "s5_committers",
        "s6_open_issues",
        "s6_closed_issues",
    }


def test_six_without_github_is_dead_by_score_and_unverified() -> None:
    signals, warnings = no_github_variant(
        _loaded(anchor_copy("six"), registry=None, archived=False)
    )
    assert signals.s3_last_push_at is None
    assert signals.s5_committers is None
    assert signals.s6_open_issues is None
    assert signals.s6_closed_issues is None
    assert signals.s1_declared_death is None
    result = score_package(signals)
    assert result.base_state is BaseState.DEAD
    assert result.dead_reason == "score"
    assert unverified_sources(result, signals, warnings) == ("github",)
    assert [w.code for w in warnings] == ["GITHUB_DISABLED"]
    assert warnings[0].source == "github"
    assert set(warnings[0].signals) == set(FEEDS["github"])


def test_nose_without_github_is_unchanged_and_has_no_github_warning() -> None:
    loaded = _loaded(anchor_copy("nose"), registry=None, archived=None)
    assert loaded.raw["repo"] is None
    signals, warnings = no_github_variant(loaded)
    assert signals == loaded.signals
    assert not any(w.source == "github" or w.code == "GITHUB_DISABLED" for w in warnings)
    result = score_package(signals)
    assert result.dead_reason == "score"
    assert unverified_sources(result, signals, warnings) == ()


def test_registry_deprecated_keeps_declared_death() -> None:
    loaded = _loaded(anchor_copy("request"), registry=True, archived=False)
    signals, warnings = no_github_variant(loaded)
    assert signals.s1_declared_death is True
    result = score_package(signals)
    assert result.base_state is BaseState.DEAD
    assert result.dead_reason == "declared"
    assert [w.code for w in warnings] == ["GITHUB_DISABLED"]
    assert set(warnings[0].signals) == set(FEEDS["github"])


def test_archived_only_death_is_lost_without_github() -> None:
    loaded = _loaded(anchor_copy("left-pad"), registry=False, archived=True)
    assert score_package(loaded.signals).dead_reason == "declared"
    signals, _ = no_github_variant(loaded)
    assert signals.s1_declared_death is None
    assert score_package(signals).dead_reason != "declared"


def test_derivation_keeps_non_github_warnings_and_adds_one_disabled() -> None:
    raw = anchor_copy(
        "six",
        s3_last_push_at=_null(unavailable=True),
        s2_latest_release_at=_null("https://api.deps.dev/v3/x", unavailable=True),
    )
    _, warnings = no_github_variant(_loaded(raw))
    assert [(w.code, w.source) for w in warnings] == [
        ("INTERNAL_ERROR", "depsdev"),
        ("GITHUB_DISABLED", "github"),
    ]


# --- errors (EV-RUN-3) ---------------------------------------------------------------------


def _set(root: Path, *names: str) -> None:
    write_fixture_set(root, [{"fixture": anchor_copy(n)} for n in names])


def _keys(*pairs: tuple[str, str]) -> set[tuple[str, str]]:
    return set(pairs)


def _rewrite(path: Path, **changes: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_valid_set_loads(tmp_path: Path) -> None:
    _set(tmp_path, "six", "request")
    loaded = load_fixtures(tmp_path, _keys(("pypi", "six"), ("npm", "request")))
    assert sorted(loaded) == [("npm", "request"), ("pypi", "six")]
    assert loaded[("pypi", "six")].resolved_version == "1.17.0"
    assert loaded[("pypi", "six")].registry_deprecated is None


def test_resolved_version_is_checked_when_keys_is_a_mapping(tmp_path: Path) -> None:
    _set(tmp_path, "six")
    load_fixtures(tmp_path, {("pypi", "six"): "1.17.0"})
    with pytest.raises(FixtureError, match=r"pypi/six\.json"):
        load_fixtures(tmp_path, {("pypi", "six"): "1.16.0"})


def test_invalid_json_names_the_file(tmp_path: Path) -> None:
    _set(tmp_path, "six")
    (tmp_path / "pypi" / "six.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(FixtureError, match=r"pypi/six\.json"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))


def test_orphan_file_names_the_file(tmp_path: Path) -> None:
    _set(tmp_path, "six", "nose")
    with pytest.raises(FixtureError, match=r"pypi/nose\.json"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))


def test_missing_file_names_the_file(tmp_path: Path) -> None:
    _set(tmp_path, "six")
    with pytest.raises(FixtureError, match=r"pypi/nose\.json"):
        load_fixtures(tmp_path, _keys(("pypi", "six"), ("pypi", "nose")))


def test_ecosystem_mismatch_names_the_file(tmp_path: Path) -> None:
    _set(tmp_path, "six")
    _rewrite(tmp_path / "pypi" / "six.json", ecosystem="npm")
    with pytest.raises(FixtureError, match=r"pypi/six\.json.*ecosystem"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))


def test_package_mismatch_names_the_file(tmp_path: Path) -> None:
    _set(tmp_path, "six")
    _rewrite(tmp_path / "pypi" / "six.json", package="seven")
    with pytest.raises(FixtureError, match=r"pypi/six\.json.*package"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))


def test_resolved_version_mismatch_names_the_file(tmp_path: Path) -> None:
    _set(tmp_path, "six")
    with pytest.raises(FixtureError, match=r"pypi/six\.json.*resolved_version"):
        load_fixtures(tmp_path, {("pypi", "six"): "9.9.9"})


def test_missing_s1_parts_names_the_file(tmp_path: Path) -> None:
    _set(tmp_path, "six")
    path = tmp_path / "pypi" / "six.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["s1_parts"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FixtureError, match=r"pypi/six\.json.*s1_parts"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))


def test_two_as_of_values_name_a_file(tmp_path: Path) -> None:
    _set(tmp_path, "six", "nose")
    _rewrite(tmp_path / "pypi" / "nose.json", as_of="2026-11-04")
    with pytest.raises(FixtureError, match=r"pypi/(six|nose)\.json.*as_of"):
        load_fixtures(tmp_path, _keys(("pypi", "six"), ("pypi", "nose")))


def test_unmappable_signals_name_the_file(tmp_path: Path) -> None:
    write_fixture_set(
        tmp_path,
        [{"fixture": anchor_copy("six", s5_committers={**_null(), "value": -1})}],
    )
    with pytest.raises(FixtureError, match=r"pypi/six\.json"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))


def _s1_parts_rewrite(tmp_path: Path, parts: Any) -> None:
    _set(tmp_path, "six")
    _rewrite(tmp_path / "pypi" / "six.json", s1_parts=parts)


def test_s1_parts_entry_without_value_names_the_file(tmp_path: Path) -> None:
    _s1_parts_rewrite(
        tmp_path, {"registry_deprecated": {"note": "x"}, "repo_archived": {"value": False}}
    )
    with pytest.raises(FixtureError, match=r"pypi/six\.json.*needs registry_deprecated"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))


def test_s1_parts_registry_value_must_be_bool_or_null(tmp_path: Path) -> None:
    _s1_parts_rewrite(
        tmp_path,
        {"registry_deprecated": {"value": "yes"}, "repo_archived": {"value": False}},
    )
    with pytest.raises(FixtureError, match=r"pypi/six\.json.*true, false or null"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))


def test_fixture_that_is_not_a_json_object_names_the_file(tmp_path: Path) -> None:
    _set(tmp_path, "six")
    (tmp_path / "pypi" / "six.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(FixtureError, match=r"pypi/six\.json.*must be a JSON object"):
        load_fixtures(tmp_path, _keys(("pypi", "six")))
