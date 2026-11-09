"""Property tests for the Purl model (PV-INV-1 value half, PV-INV-5 name part)."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.purl.model import Purl, normalise_pypi_name
from core.purl.tests.strategies import purls, pypi_names

pytestmark = pytest.mark.property

_SEP_RUN = re.compile(r"[-_.]+")


@given(purls())
def test_purl_values_valid(p: Purl) -> None:
    """Every generated value constructs, and re-validating it is a fixed point.

    **Validates: Requirements PV-INV-1**
    """
    again = dataclasses.replace(p)
    assert again == p
    assert hash(again) == hash(p)
    assert Purl(p.ecosystem, p.namespace, p.name, p.version, p.qualifiers, p.subpath) == p


def _invalid_changes(p: Purl) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = [
        {"ecosystem": "maven"},
        {"ecosystem": 1},
        {"name": ""},
        {"name": p.name + "/x"},
        {"name": 5},
        {"name": p.name + " x"},
        {"version": ""},
        {"version": "1 .0"},
        {"version": 1},
        {"qualifiers": (("b", "1"), ("a", "2"))},
        {"qualifiers": (("a", "1"), ("a", "2"))},
        {"qualifiers": (("A", "1"),)},
        {"qualifiers": (("a", ""),)},
        {"qualifiers": (("a", " x "),)},
        {"qualifiers": [("a", "1")]},
        {"subpath": ""},
        {"subpath": "."},
        {"subpath": "a/../b"},
        {"subpath": "a//b"},
        {"subpath": 3},
    ]
    if p.ecosystem == "npm":
        changes += [
            {"namespace": "scope"},
            {"namespace": "@"},
            {"namespace": "@a@b"},
            {"namespace": "@a/b"},
            {"name": p.name + "@"},
        ]
    else:
        changes += [
            {"namespace": "@scope"},
            {"name": p.name + "_X"},
            {"name": p.name.upper() + "A"},
        ]
    return changes


@st.composite
def _mutated(draw: st.DrawFn) -> tuple[Purl, dict[str, Any]]:
    p = draw(purls())
    return p, draw(st.sampled_from(_invalid_changes(p)))


@given(_mutated())
def test_purl_invalid_fields_raise_value_error(case: tuple[Purl, dict[str, Any]]) -> None:
    """Flipping one field to an invalid value raises ValueError and nothing else.

    **Validates: Requirements PV-INV-1**
    """
    p, change = case
    with pytest.raises(ValueError):
        dataclasses.replace(p, **change)


@given(pypi_names())
def test_pep503_idempotent(name: str) -> None:
    """**Validates: Requirements PV-INV-5**"""
    once = normalise_pypi_name(name)
    assert normalise_pypi_name(once) == once


@st.composite
def _variant_pairs(draw: st.DrawFn) -> tuple[str, str]:
    """A name and a variant differing only in ASCII case and separator-run content."""
    name = draw(pypi_names())
    flips = draw(st.lists(st.booleans(), min_size=len(name), max_size=len(name)))
    cased = "".join(c.swapcase() if f else c for c, f in zip(name, flips, strict=True))
    runs = st.text(st.sampled_from("-_."), min_size=1, max_size=4)

    parts: list[str] = []
    last = 0
    for m in _SEP_RUN.finditer(cased):
        parts.append(cased[last : m.start()])
        parts.append(draw(runs))
        last = m.end()
    parts.append(cased[last:])
    return name, "".join(parts)


@given(_variant_pairs())
def test_pep503_variants_collapse(pair: tuple[str, str]) -> None:
    """Names differing only in case or separator runs normalise equal (name part).

    **Validates: Requirements PV-INV-5**
    """
    a, b = pair
    na, nb = normalise_pypi_name(a), normalise_pypi_name(b)
    assert na == nb
    assert Purl("pypi", None, na, None) == Purl("pypi", None, nb, None)
