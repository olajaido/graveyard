"""Unit tests for cli.text.sanitise (CLI-OUT-8)."""

from __future__ import annotations

import pytest

from cli.text import REPLACEMENT, sanitise


@pytest.mark.parametrize(
    "char",
    ["\x00", "\x1b", "\x7f", "\x85", "\u202e", "\u2066", "\t"],
    ids=["NUL", "ESC", "DEL", "C1-NEL", "U+202E", "U+2066", "tab"],
)
def test_forbidden_character_is_replaced(char: str) -> None:
    assert sanitise(f"a{char}b") == f"a{REPLACEMENT}b"


@pytest.mark.parametrize(
    "text",
    ["plain letters", "café", "\U0001f468\u200d\U0001f469\u200d\U0001f467", ""],
    ids=["letters", "e-acute", "emoji-zwj-sequence", "empty"],
)
def test_kept_characters_are_unchanged(text: str) -> None:
    assert sanitise(text) == text


def test_replacement_character_is_kept() -> None:
    assert sanitise(REPLACEMENT) == REPLACEMENT
