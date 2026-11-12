"""``pick_latest`` and the latest-version parsers (KPW-RES-2)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.sources.facts import RegistryLatest, is_valid_version
from core.sources.latest import pick_latest
from core.sources.parse.registry import parse_npm_latest, parse_pypi_latest

_VALID = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9._+!~-]{0,99}", fullmatch=True)
_ANY = st.one_of(st.none(), st.text(max_size=120), st.integers())


def test_registry_wins_over_depsdev() -> None:
    assert pick_latest("5.3.0", "4.22.3") == ("5.3.0", "registry")


def test_depsdev_when_registry_unusable() -> None:
    assert pick_latest(None, "1.2") == ("1.2", "depsdev")
    assert pick_latest("bad version!", "1.2") == ("1.2", "depsdev")
    assert pick_latest(7, "1.2") == ("1.2", "depsdev")


def test_none_when_neither_usable() -> None:
    assert pick_latest(None, None) == (None, None)
    assert pick_latest("", "has space") == (None, None)


@pytest.mark.property
@given(registry=_VALID, other=_ANY)
def test_a_usable_registry_version_always_wins(registry: str, other: object) -> None:
    assert pick_latest(registry, other) == (registry, "registry")


@pytest.mark.property
@given(registry=_ANY, other=_ANY)
def test_none_only_when_neither_is_usable(registry: object, other: object) -> None:
    version, via = pick_latest(registry, other)
    usable = [v for v in (registry, other) if isinstance(v, str) and is_valid_version(v)]
    assert (version is None) == (not usable)
    assert (via is None) == (version is None)
    if version is not None:
        assert version in usable


def test_parse_npm_latest() -> None:
    assert parse_npm_latest({"dist-tags": {"latest": "5.3.0", "latest-4": "4.22.3"}}) == (
        RegistryLatest("5.3.0")
    )
    assert parse_npm_latest({"dist-tags": {"latest": "no good"}}) == RegistryLatest(None)
    assert parse_npm_latest({}) == RegistryLatest(None)
    assert parse_npm_latest([]) is None


def test_parse_pypi_latest() -> None:
    assert parse_pypi_latest({"info": {"version": "1.17.0"}}) == RegistryLatest("1.17.0")
    assert parse_pypi_latest({"info": {"version": 3}}) == RegistryLatest(None)
    assert parse_pypi_latest({}) == RegistryLatest(None)
    assert parse_pypi_latest("x") is None


def test_registry_latest_json_round_trip() -> None:
    fact = RegistryLatest("1.0.0")
    assert RegistryLatest.from_json(fact.to_json()) == fact
    assert RegistryLatest.from_json({"version": 5}) is None
