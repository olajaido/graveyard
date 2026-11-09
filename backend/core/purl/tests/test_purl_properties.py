"""Property tests for purl parse/format/normalise (PV-INV-1 to 4 and 6).

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
"""

from __future__ import annotations

import dataclasses
from urllib.parse import quote

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from core.purl.model import Purl
from core.purl.purl import format_purl, normalise_purl, package_key, parse_purl, registry_name
from core.purl.tests.strategies import (
    ascii_case_flip,
    disallowed_type_purls,
    invalid_purl_strings,
    purl_strings,
    purls,
    qualifiers,
    subpaths,
)

pytestmark = pytest.mark.property


@given(purl_strings())
def test_purl_round_trip(case: tuple[str, str]) -> None:
    """``format_purl(parse_purl(s)) == normalise_purl(s)``.

    **Validates: Requirements PV-INV-1**
    """
    s, _ = case
    assert format_purl(parse_purl(s)) == normalise_purl(s)


@given(purl_strings())
def test_purl_matches_oracle(case: tuple[str, str]) -> None:
    """``normalise_purl(s)`` equals the independently built canonical string.

    **Validates: Requirements PV-INV-1**
    """
    s, expected = case
    assert normalise_purl(s) == expected


@given(purls())
def test_purl_value_round_trip(p: Purl) -> None:
    """``parse_purl(format_purl(p)) == p``.

    **Validates: Requirements PV-INV-1**
    """
    assert parse_purl(format_purl(p)) == p


@given(purl_strings())
def test_normalise_purl_idempotent(case: tuple[str, str]) -> None:
    """**Validates: Requirements PV-INV-2**"""
    once = normalise_purl(case[0])
    assert normalise_purl(once) == once


@given(purl_strings())
def test_parse_valid_never_raises(case: tuple[str, str]) -> None:
    """**Validates: Requirements PV-INV-3**"""
    assert isinstance(parse_purl(case[0]), Purl)


_SURROGATE_TEXT = st.text(
    st.one_of(st.characters(codec=None), st.characters(categories=["Cs"])), max_size=30
)


@example("pkg:npm/\ud800@1")
@given(st.one_of(invalid_purl_strings(), _SURROGATE_TEXT))
def test_parse_only_raises_value_error(s: str) -> None:
    """``parse_purl`` returns a ``Purl`` or raises ``ValueError``, nothing else.

    **Validates: Requirements PV-INV-4**
    """
    try:
        result = parse_purl(s)
    except ValueError:
        return
    assert isinstance(result, Purl)


@given(disallowed_type_purls())
def test_parse_rejects_other_ecosystems(s: str) -> None:
    """Types outside npm and pypi always raise ``ValueError``.

    **Validates: Requirements PV-INV-4**
    """
    with pytest.raises(ValueError):
        parse_purl(s)


@given(purls().filter(lambda p: p.ecosystem == "npm"), st.sampled_from(["@", "%40"]))
def test_npm_case_preserved(p: Purl, scope_prefix: str) -> None:
    """Parsed npm namespace and name equal the input exactly, and format keeps case.

    **Validates: Requirements PV-INV-6**
    """
    parsed = parse_purl(format_purl(p))
    assert parsed.namespace == p.namespace
    assert parsed.name == p.name

    # Hand-written spelling of the same purl, with either scope encoding.
    s = "pkg:npm/"
    if p.namespace:
        s += scope_prefix + quote(p.namespace[1:], safe="") + "/"
    s += quote(p.name, safe="")
    again = parse_purl(s)
    assert again.namespace == p.namespace
    assert again.name == p.name
    out = format_purl(again)
    reparsed = parse_purl(out)
    assert (reparsed.namespace, reparsed.name) == (p.namespace, p.name)


# ---------------------------------------------------------------------------
# PV-INV-7, PV-INV-8, PV-INV-14: package_key and registry_name
# ---------------------------------------------------------------------------

_ASCII_LOWER = {ord(c): ord(c) + 32 for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


def _lower(text: str | None) -> str | None:
    """Test-local ASCII-only lower-casing (does not touch non-ASCII letters)."""
    return None if text is None else text.translate(_ASCII_LOWER)


def _expected_key_purl(p: Purl) -> Purl:
    """``p`` without qualifiers/subpath; npm namespace and name ASCII-lower-cased."""
    k = dataclasses.replace(p, qualifiers=(), subpath=None)
    if p.ecosystem == "npm":
        k = dataclasses.replace(k, namespace=_lower(p.namespace), name=str(_lower(p.name)))
    return k


_npm_purls = purls().filter(lambda p: p.ecosystem == "npm")
_npm_with_flip = _npm_purls.flatmap(lambda p: st.tuples(st.just(p), ascii_case_flip(p)))


@given(purls(), qualifiers(), subpaths(), qualifiers(), subpaths())
def test_package_key_ignores_qualifiers_subpath(
    p: Purl,
    q1: tuple[tuple[str, str], ...],
    s1: str | None,
    q2: tuple[tuple[str, str], ...],
    s2: str | None,
) -> None:
    """**Validates: Requirements PV-INV-7**"""
    a = dataclasses.replace(p, qualifiers=q1, subpath=s1)
    b = dataclasses.replace(p, qualifiers=q2, subpath=s2)
    assert package_key(a) == package_key(b)


@given(purl_strings())
def test_package_key_idempotent_under_normalise(case: tuple[str, str]) -> None:
    """**Validates: Requirements PV-INV-7**"""
    s, _ = case
    assert package_key(parse_purl(normalise_purl(s))) == package_key(parse_purl(s))


@given(purls())
def test_package_key_reversible(p: Purl) -> None:
    """Parsing ``pkg:`` + key gives ``p`` minus qualifiers/subpath, npm names folded.

    **Validates: Requirements PV-INV-7**
    """
    assert parse_purl("pkg:" + package_key(p)) == _expected_key_purl(p)


@given(purls())
def test_package_key_stable_under_rekey(p: Purl) -> None:
    """**Validates: Requirements PV-INV-7**"""
    k = package_key(p)
    assert package_key(parse_purl("pkg:" + k)) == k


@given(purls())
def test_registry_name_round_trip(p: Purl) -> None:
    """**Validates: Requirements PV-INV-8**"""
    assert registry_name(parse_purl(format_purl(p))) == registry_name(p)


@given(_npm_purls)
def test_registry_name_npm_shape(p: Purl) -> None:
    """Scoped iff exactly one ``/``; scoped names start with ``@``.

    **Validates: Requirements PV-INV-8**
    """
    r = registry_name(p)
    assert (r.count("/") == 1) == (p.namespace is not None)
    assert r.count("/") <= 1
    if p.namespace is not None:
        assert r.startswith("@")


@given(_npm_with_flip)
def test_package_key_npm_case_insensitive(pair: tuple[Purl, Purl]) -> None:
    """**Validates: Requirements PV-INV-14**"""
    p, flipped = pair
    assert package_key(p) == package_key(flipped)


@given(_npm_purls)
def test_package_key_npm_version_and_non_ascii_not_folded(p: Purl) -> None:
    """Version case and non-ASCII letter case are never folded.

    **Validates: Requirements PV-INV-14**
    """
    if p.version is not None:
        swapped = p.version.swapcase()
        if swapped != p.version:
            try:
                other = dataclasses.replace(p, version=swapped)
            except ValueError:
                other = None
            if other is not None:
                assert package_key(p) != package_key(other)

    def swap_non_ascii(t: str) -> str:
        return "".join(c.swapcase() if not c.isascii() else c for c in t)

    ns = None if p.namespace is None else swap_non_ascii(p.namespace)
    name = swap_non_ascii(p.name)
    if (ns, name) != (p.namespace, p.name):
        try:
            other = dataclasses.replace(p, namespace=ns, name=name)
        except ValueError:
            assume(False)
        assert package_key(p) != package_key(other)


@given(_npm_with_flip)
def test_package_key_keeps_case_in_other_outputs(pair: tuple[Purl, Purl]) -> None:
    """**Validates: Requirements PV-INV-14**"""
    p, flipped = pair
    assume((flipped.namespace, flipped.name) != (p.namespace, p.name))
    assert format_purl(flipped) != format_purl(p)
    assert registry_name(flipped) != registry_name(p)


@given(purls().filter(lambda p: p.ecosystem == "pypi"))
def test_package_key_pypi_unchanged(p: Purl) -> None:
    """**Validates: Requirements PV-INV-14**"""
    assert package_key(p).split("/", 1)[1].split("@", 1)[0] == p.name
