"""Property tests for ``cli.text.sanitise`` (CLI-OUT-8, D13).

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
"""

from __future__ import annotations

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.text import REPLACEMENT, sanitise

pytestmark = pytest.mark.property

_BIDI = [chr(cp) for cp in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))]

# Surrogate-free by construction (``Cs`` excluded), biased towards the classes that
# matter: C0, DEL, C1, bidi controls, ZWJ and the replacement character itself.
_TEXT = st.text(
    st.one_of(
        st.characters(codec="utf-8"),  # excludes surrogates
        st.characters(max_codepoint=0xA0),
        st.sampled_from(_BIDI + ["\u200d", REPLACEMENT, "\x1b", "\x00", "\x7f", "\x85"]),
    ),
    max_size=60,
)


def _forbidden(char: str) -> bool:
    return char in _BIDI or unicodedata.category(char) == "Cc"


@given(_TEXT)
def test_sanitise_idempotent(text: str) -> None:
    """``sanitise(sanitise(t)) == sanitise(t)``.

    **Validates: Requirements CLI-OUT-8**
    """
    once = sanitise(text)
    assert sanitise(once) == once


@given(_TEXT)
def test_sanitise_removes_forbidden(text: str) -> None:
    """No ``Cc`` or bidi control character survives; all others are kept in place.

    **Validates: Requirements CLI-OUT-8**
    """
    out = sanitise(text)
    assert not any(_forbidden(c) for c in out)
    for before, after in zip(text, out, strict=True):
        assert after == (REPLACEMENT if _forbidden(before) else before)


@given(_TEXT)
def test_sanitise_length_preserving(text: str) -> None:
    """The output has the same number of characters as the input.

    **Validates: Requirements CLI-OUT-8**
    """
    assert len(sanitise(text)) == len(text)
