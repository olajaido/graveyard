"""Unit tests for ``core.sources.secret`` (SRC-SEC-1, SRC-SEC-3)."""

from __future__ import annotations

import copy
import pickle
from dataclasses import asdict, dataclass
from typing import Any

import pytest

from core.sources.secret import MAX_TOKEN_LENGTH, REDACTED, SecretToken, redact

# Built at runtime so no token-shaped literal sits in the source file.
TOKEN = "tok" + "-distinctive-" + "9f3b2c1d"
SHAPED = [
    "ghp_" + "A" * 36,
    "gho_" + "b" * 25,
    "ghu_" + "C1" * 15,
    "ghs_" + "d" * 20,
    "ghr_" + "E" * 40,
    "github_pat_" + "A1_" * 10,
]


# --- construction -------------------------------------------------------------------------


def test_reveal_returns_the_value() -> None:
    assert SecretToken(TOKEN).reveal() == TOKEN


def test_maximum_length_token_is_accepted() -> None:
    assert SecretToken("x" * MAX_TOKEN_LENGTH).reveal() == "x" * MAX_TOKEN_LENGTH


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " ",
        "secret value",
        "secret\tvalue",
        "secret\nvalue",
        "secret\x00value",
        "secret\x7fvalue",
        "secret\u200bvalue",
        "secret\u2028value",
        "s" * (MAX_TOKEN_LENGTH + 1),
        123,
        None,
        b"secret",
    ],
)
def test_invalid_token_is_rejected_without_echo(bad: object) -> None:
    value: Any = bad
    with pytest.raises(ValueError) as info:
        SecretToken(value)
    message = str(info.value)
    if isinstance(bad, str) and bad.strip():
        assert bad not in message
        assert "secret" not in message


# --- redacted display ---------------------------------------------------------------------


def test_repr_str_and_format_are_redacted() -> None:
    token = SecretToken(TOKEN)
    assert repr(token) == "SecretToken(***)"
    assert str(token) == "SecretToken(***)"
    assert f"{token}" == "SecretToken(***)"
    assert "%s" % token == "SecretToken(***)"  # noqa: UP031
    assert "%r" % token == "SecretToken(***)"  # noqa: UP031
    assert "{}".format(token) == "SecretToken(***)"  # noqa: UP032


@pytest.mark.parametrize("spec", ["", ">40", "<40", "^40", "x", "10.3", "*^30", "s"])
def test_format_specs_do_not_reveal(spec: str) -> None:
    token = SecretToken(TOKEN)
    assert TOKEN not in format(token, spec)
    assert TOKEN not in f"{token:{spec}}"


def test_container_repr_is_redacted() -> None:
    token = SecretToken(TOKEN)
    assert TOKEN not in repr([token]) + repr({"k": token}) + repr((token,))


def test_token_inside_dataclass_repr_is_redacted() -> None:
    @dataclass
    class Holder:
        token: SecretToken

    assert TOKEN not in repr(Holder(SecretToken(TOKEN)))


# --- pickling, copying, mutation ----------------------------------------------------------


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_pickling_is_refused(protocol: int) -> None:
    with pytest.raises(TypeError):
        pickle.dumps(SecretToken(TOKEN), protocol=protocol)


def test_copy_and_deepcopy_are_refused() -> None:
    token = SecretToken(TOKEN)
    with pytest.raises(TypeError):
        copy.copy(token)
    with pytest.raises(TypeError):
        copy.deepcopy(token)


def test_asdict_cannot_copy_the_token_out() -> None:
    @dataclass
    class Holder:
        token: SecretToken

    with pytest.raises(TypeError):
        asdict(Holder(SecretToken(TOKEN)))


def test_token_is_immutable() -> None:
    token: Any = SecretToken(TOKEN)
    with pytest.raises(AttributeError):
        token._value = "other"
    with pytest.raises(AttributeError):
        token.extra = 1
    with pytest.raises(AttributeError):
        del token._value
    assert token.reveal() == TOKEN


# --- redact -------------------------------------------------------------------------------


def test_redact_exact_string_token() -> None:
    assert redact(f"Authorization: bearer {TOKEN} end", TOKEN) == (
        f"Authorization: bearer {REDACTED} end"
    )


def test_redact_exact_secret_token() -> None:
    out = redact(f"a {TOKEN} b {TOKEN}", SecretToken(TOKEN))
    assert TOKEN not in out
    assert out == f"a {REDACTED} b {REDACTED}"


def test_redact_without_token_leaves_plain_text() -> None:
    assert redact("nothing to see") == "nothing to see"
    assert redact("nothing to see", None) == "nothing to see"
    assert redact("nothing to see", "") == "nothing to see"
    assert redact("") == ""


@pytest.mark.parametrize("shaped", SHAPED)
def test_redact_shaped_tokens(shaped: str) -> None:
    out = redact(f"before {shaped} after")
    assert shaped not in out
    assert out == f"before {REDACTED} after"


@pytest.mark.parametrize("short", ["ghp_" + "A" * 19, "github_pat_" + "A" * 19, "ghx_" + "A" * 30])
def test_redact_leaves_near_misses(short: str) -> None:
    assert redact(short) == short


def test_redact_exact_then_shape() -> None:
    shaped = SHAPED[0]
    out = redact(f"{TOKEN} {shaped}", TOKEN)
    assert out == f"{REDACTED} {REDACTED}"


@pytest.mark.parametrize(
    ("token", "text", "expected"),
    [
        ("RED", "xREDy", "xy"),
        ("RED", "RED", ""),
        ("ACTED", "ACTEDACTED", ""),
        ("[REDACTED]", "a[REDACTED]b", "ab"),
        ("D", "ADD", "A"),
    ],
)
def test_redact_token_that_is_a_placeholder_substring(token: str, text: str, expected: str) -> None:
    out = redact(text, token)
    assert out == expected
    assert token not in out


def test_redact_deleting_a_placeholder_substring_cannot_rebuild_the_token() -> None:
    # Removing the inner "RED" joins "RE" and "D" into a new "RED"; it must go too.
    out = redact("RERED" + "D", "RED")
    assert "RED" not in out


# Regressions found by ``test_redact_removes_token*`` in test_properties_foundation.py.
@pytest.mark.parametrize(
    ("token", "text"),
    [
        # Replacing "0[" by the placeholder leaves "0[" in front of the next "REDACTED".
        ("0[", "0[00["),
        ("x[", "xx["),
        # The placeholder followed by one more character forms the token again.
        (REDACTED + "x", REDACTED + "xx"),
        # The shape pass puts "[REDACTED]" back, which contains the token "A".
        ("A", "A" + "github_pat_" + "0" * 20),
    ],
)
def test_redact_result_never_contains_the_token(token: str, text: str) -> None:
    for given in (token, SecretToken(token)):
        out = redact(text, given)
        assert token not in out
        assert not any(shape in out for shape in SHAPED)
