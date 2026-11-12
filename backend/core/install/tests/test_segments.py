"""Pinned ``shlex`` behaviours behind design 4.2, and ``split`` rows built on them.

The first table records what ``shlex`` actually does (observed in the T4.2
scratch script). Those rows are why ``segments.split`` uses its own quote-aware
operator scanner and calls ``shlex.split`` only between operators.
"""

from __future__ import annotations

import shlex

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.install.segments import split


def _lex(text: str, *, punct: bool | str = False, whitespace: str | None = None) -> list[str]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=punct)
    if whitespace is not None:
        lexer.whitespace = whitespace
    lexer.whitespace_split = True
    return list(lexer)


SHLEX_ROWS: list[tuple[str, dict[str, object], list[str]]] = [
    # custom punctuation_chars splits operators into their own tokens
    (
        "a && b || c ; d | e & f",
        {"punct": ";&|"},
        ["a", "&&", "b", "||", "c", ";", "d", "|", "e", "&", "f"],
    ),
    # a quoted operator is not split, but a lone quoted ';' equals a real one
    ("echo 'a;b' && c", {"punct": ";&|"}, ["echo", "a;b", "&&", "c"]),
    ("echo ';' c", {"punct": ";&|"}, ["echo", ";", "c"]),
    # default whitespace includes newline, so newline is lost as a separator
    ("a b\nc", {"punct": True}, ["a", "b", "c"]),
    # whitespace reassigned after construction: newline glues into the word
    ("a b\nc", {"punct": True, "whitespace": " \t\r"}, ["a", "b\nc"]),
    ("a\nb", {"punct": ";&|", "whitespace": " \t\r"}, ["a\nb"]),
    # 2>&1 with punctuation_chars=True and with ";&|"
    ("npm i x 2>&1 | tail", {"punct": True}, ["npm", "i", "x", "2", ">&", "1", "|", "tail"]),
    ("npm i x 2>&1 | tail", {"punct": ";&|"}, ["npm", "i", "x", "2>", "&", "1", "|", "tail"]),
    # "$(" is split only when punctuation_chars=True
    ("echo $(date) x", {"punct": True}, ["echo", "$", "(", "date", ")", "x"]),
    ("echo $(date) x", {}, ["echo", "$(date)", "x"]),
]


@pytest.mark.parametrize(("text", "kwargs", "expected"), SHLEX_ROWS)
def test_shlex_observed_tokens(text: str, kwargs: dict[str, object], expected: list[str]) -> None:
    assert _lex(text, **kwargs) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("text", ["echo 'abc", 'echo "abc', "echo abc\\"])
def test_shlex_unbalanced_raises(text: str) -> None:
    with pytest.raises(ValueError):
        _lex(text)


def test_shlex_comment_swallows_newline() -> None:
    lexer = shlex.shlex("a # c\nb", posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    assert list(lexer) == ["a", "b"]  # the newline vanished with the comment


SPLIT_ROWS: list[tuple[str, tuple[tuple[str, ...], ...]]] = [
    ("npm install a && npm install b", (("npm", "install", "a"), ("npm", "install", "b"))),
    ("a || b ; c | d & e", (("a",), ("b",), ("c",), ("d",), ("e",))),
    ("a\nb", (("a",), ("b",))),
    ("echo 'a;b' && c", (("echo", "a;b"), ("c",))),
    ("echo ';' c", (("echo", ";", "c"),)),
    ("npm i x 2>&1 | tail", (("npm", "i", "x"), ("tail",))),
    ("echo $(date) x", ()),
    ("a # c\nb", (("a",), ("b",))),
    ("echo 'abc", ()),
    ('echo "abc', ()),
    ("echo abc\\", ()),
]


@pytest.mark.parametrize(("command", "expected"), SPLIT_ROWS)
def test_split_rows(command: str, expected: tuple[tuple[str, ...], ...]) -> None:
    assert split(command) == expected


MORE_SPLIT_ROWS: list[tuple[str, tuple[tuple[str, ...], ...]]] = [
    ("", ()),
    ("   ", ()),
    # '(' ')' '<<' poison only their own segment
    ("(a)", ()),
    ("a (b) c", ()),
    ("a && (b)", (("a",),)),
    ("(a) && b", (("b",),)),
    ("cat <<EOF", ()),
    ("cat <<-EOF && b", (("b",),)),
    # control characters become the skip marker; \r is whitespace
    ("a \x01b", (("a", "\x00"),)),
    ("a b\x7f", (("a", "\x00"),)),
    ("a\rb", (("a", "b"),)),
    ("a\tb", (("a", "b"),)),
    # operators, quoted and escaped
    ('a "b && c"', (("a", "b && c"),)),
    ("a 'b | c' d", (("a", "b | c", "d"),)),
    ("a\\;b", (("a;b",),)),
    ("a\\\nb", (("\x00",),)),
    ("a &&& b", (("a",), ("b",))),
    ("a;;b", (("a",), ("b",))),
    ("a &\nb", (("a",), ("b",))),
    # redirection tails, with and without a preceding digit token
    ("a > out && b", (("a",), ("b",))),
    ("a 2> err", (("a",),)),
    ("a 2>&1", (("a",),)),
    ("a &> f", (("a",),)),
    ("a >> f b", (("a",),)),
    ("a < in", (("a",),)),
    ("a 12> f", (("a",),)),
    ("a 12 > f", (("a", "12"),)),
    ("a2 > f", (("a2",),)),
    # comments
    ("a #c", (("a",),)),
    ("a#b", (("a#b",),)),
    ("# only", ()),
    ("a # c && d\nb", (("a",), ("b",))),
    ("a '#b'", (("a", "#b"),)),
]


@pytest.mark.parametrize(("command", "expected"), MORE_SPLIT_ROWS)
def test_split_more_rows(command: str, expected: tuple[tuple[str, ...], ...]) -> None:
    assert split(command) == expected


def test_split_non_str_is_empty() -> None:
    assert split(None) == ()  # type: ignore[arg-type]


@pytest.mark.property
@given(st.text())
def test_split_total_over_text(command: str) -> None:
    result = split(command)
    assert all(seg and all(isinstance(w, str) for w in seg) for seg in result)


@pytest.mark.property
@given(st.text(alphabet="ab '\"\\;&|<>()#\n\r\t$0123456789\x01", max_size=60))
def test_split_total_over_operator_heavy_text(command: str) -> None:
    assert isinstance(split(command), tuple)
