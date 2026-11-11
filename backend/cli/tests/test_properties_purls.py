"""Property tests for ``cli.purls.validate_purls`` (CLI-PURL-2, CLI-PURL-3).

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
"""

from __future__ import annotations

import dataclasses
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.errors import UsageError
from cli.purls import validate_purls
from core.purl import format_purl, package_key, parse_purl
from core.purl.tests.strategies import invalid_purl_strings, purl_strings, purls

pytestmark = pytest.mark.property


@st.composite
def _versioned_canonical(draw: st.DrawFn) -> str:
    p = draw(purls())
    if p.version is None:
        p = dataclasses.replace(p, version="1.0.0")
    return format_purl(p)


def _has_version(text: str) -> bool:
    return parse_purl(text).version is not None


# Valid, versioned purls: canonical and non-canonical spellings, so success paths run.
_VALID = st.one_of(
    _versioned_canonical(),
    purl_strings().map(lambda case: case[0]).filter(_has_version),
)
_VALID_LISTS = st.lists(_VALID, max_size=6)

# Arbitrary candidates: valid, mutated/invalid, plain text, versionless.
_CANDIDATES = st.lists(
    st.one_of(
        _VALID,
        invalid_purl_strings(),
        st.text(max_size=40),
        purls().map(format_purl),
    ),
    max_size=4,
)


@given(_VALID_LISTS, st.randoms(use_true_random=False))
def test_validate_purls_order_independent(raw: list[str], rnd: random.Random) -> None:
    """Any permutation of the arguments gives the same result.

    **Validates: Requirements CLI-PURL-2, CLI-PURL-3**
    """
    shuffled = list(raw)
    rnd.shuffle(shuffled)
    assert validate_purls(shuffled) == validate_purls(raw)


@given(_VALID_LISTS)
def test_validate_purls_idempotent(raw: list[str]) -> None:
    """Validating the output gives the output.

    **Validates: Requirements CLI-PURL-2, CLI-PURL-3**
    """
    once = validate_purls(raw)
    assert validate_purls(once) == once


@given(_CANDIDATES)
def test_validate_purls_rejects_or_returns_canonical(raw: list[str]) -> None:
    """Either ``UsageError``, or every result is the canonical form of an input.

    Results are sorted, unique by package key, and cover every input's package key.

    **Validates: Requirements CLI-PURL-2, CLI-PURL-3**
    """
    try:
        result = validate_purls(raw)
    except UsageError:
        return
    canonical = {format_purl(parse_purl(x)) for x in raw}
    assert set(result) <= canonical
    assert list(result) == sorted(result)
    result_keys = [package_key(parse_purl(r)) for r in result]
    assert len(result_keys) == len(set(result_keys))
    assert set(result_keys) == {package_key(parse_purl(x)) for x in raw}
