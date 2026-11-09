"""Unit tests for the Purl model (PV-PURL-2, 3, 5, 7, 8, 9, 11)."""

from __future__ import annotations

from typing import Any

import pytest

from core.purl.model import Purl, _ascii_lower, normalise_pypi_name


def make(**overrides: Any) -> Purl:
    fields: dict[str, Any] = {
        "ecosystem": "npm",
        "namespace": None,
        "name": "left-pad",
        "version": "1.0.0",
    }
    fields.update(overrides)
    return Purl(**fields)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"namespace": "@babel", "name": "core"},
        {"ecosystem": "pypi", "name": "zope-interface"},
        {"version": None},
        {"qualifiers": (("arch", "x86"), ("os", "linux"))},
        {"subpath": "lib/index.js"},
        {"name": "JSONStream"},
    ],
)
def test_valid_shapes_construct(overrides: dict[str, Any]) -> None:
    p = make(**overrides)
    assert p.name == overrides.get("name", "left-pad")


@pytest.mark.parametrize(
    "overrides",
    [
        {"ecosystem": "maven"},
        {"ecosystem": "NPM"},
        {"namespace": "babel", "name": "core"},
        {"namespace": "@"},
        {"namespace": "@a@b"},
        {"namespace": "@a/b"},
        {"ecosystem": "pypi", "namespace": "@x", "name": "foo"},
        {"name": ""},
        {"name": "a/b"},
        {"name": "a@b"},
        {"ecosystem": "pypi", "name": "Foo"},
        {"ecosystem": "pypi", "name": "a_b"},
        {"ecosystem": "pypi", "name": "a--b"},
        {"version": ""},
        {"version": "1 .0"},
        {"version": "1\n0"},
        {"version": "1\x000"},
        {"name": "a b"},
        {"namespace": "@a b", "name": "c"},
        {"qualifiers": (("b", "1"), ("a", "2"))},
        {"qualifiers": (("a", "1"), ("a", "2"))},
        {"qualifiers": (("A", "1"),)},
        {"qualifiers": (("a", ""),)},
        {"qualifiers": (("a", " x "),)},
        {"subpath": "."},
        {"subpath": "a/../b"},
        {"subpath": "a//b"},
        {"subpath": ""},
        {"subpath": "/a"},
    ],
)
def test_invalid_shapes_raise(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        make(**overrides)


def test_error_message_repr_is_truncated() -> None:
    with pytest.raises(ValueError) as exc:
        make(name="x" * 5000 + "/")
    assert len(str(exc.value)) < 250
    assert str(exc.value).endswith("...")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Zope.Interface__x", "zope-interface-x"),
        ("a_b", "a-b"),
        ("A.B-C", "a-b-c"),
        ("already-ok", "already-ok"),
    ],
)
def test_normalise_pypi_name(raw: str, expected: str) -> None:
    assert normalise_pypi_name(raw) == expected


def test_ascii_lower() -> None:
    assert _ascii_lower(None) is None
    assert _ascii_lower("AbC-Z9") == "abc-z9"
    assert _ascii_lower("\u212a") == "\u212a"  # KELVIN SIGN is not merged with 'k'
    assert "\u212a".lower() == "k"  # contrast with str.lower()
