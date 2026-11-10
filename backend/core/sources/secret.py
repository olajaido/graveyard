"""Token handling for the pure half of the source clients (SRC-SEC-1, SRC-SEC-3, design §11).

``SecretToken`` wraps the GitHub token so it cannot leak through ``repr``, ``str``,
``format``, pickling, copying or ``dataclasses.asdict``. Only the gateway calls
``reveal()``. ``redact`` removes the exact token (when given) and anything shaped
like a GitHub token. ``Evidence`` and ``SourceWarning`` apply the shape part on
construction, so even a bug upstream cannot emit a token-shaped string.

This module reads no environment.
"""

from __future__ import annotations

import re
from typing import Final, NoReturn

REDACTED: Final = "[REDACTED]"

MAX_TOKEN_LENGTH: Final = 255

# The prototype's ``_SECRET_SHAPES``: classic and fine-grained GitHub token shapes.
_SECRET_SHAPES: Final = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")

_TOKEN_REPR: Final = "SecretToken(***)"


def _is_valid_token(value: object) -> bool:
    """True for a string of 1 to 255 characters with no whitespace or control characters."""
    if not isinstance(value, str) or not 0 < len(value) <= MAX_TOKEN_LENGTH:
        return False
    # ``isprintable`` is False for control, format, surrogate and non-space separator characters.
    return not any(ch.isspace() or not ch.isprintable() for ch in value)


class SecretToken:
    """An opaque wrapper around a secret string (not a dataclass, so ``asdict`` cannot reach it).

    ``repr``, ``str`` and ``format`` give ``SecretToken(***)`` whatever the format spec.
    The value is immutable, cannot be pickled or copied, and is returned only by
    ``reveal()``. Construction errors never include the offending value.
    """

    __slots__ = ("_value",)

    _value: str

    def __init__(self, value: str) -> None:
        if not _is_valid_token(value):
            raise ValueError(
                f"token must be a non-empty string of at most {MAX_TOKEN_LENGTH} characters "
                "without whitespace or control characters"
            )
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        """Return the raw token. Only the HTTP gateway may call this (SRC-SEC-1)."""
        return self._value

    def __repr__(self) -> str:
        return _TOKEN_REPR

    def __str__(self) -> str:
        return _TOKEN_REPR

    def __format__(self, format_spec: str) -> str:
        return _TOKEN_REPR

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SecretToken is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SecretToken is immutable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("SecretToken cannot be pickled")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("SecretToken cannot be pickled")

    def __getstate__(self) -> NoReturn:
        raise TypeError("SecretToken cannot be pickled")

    def __copy__(self) -> NoReturn:
        raise TypeError("SecretToken cannot be copied")

    def __deepcopy__(self, memo: object) -> NoReturn:
        raise TypeError("SecretToken cannot be copied")


def redact(text: str, token: str | SecretToken | None = None) -> str:
    """Return ``text`` without the exact ``token`` and without GitHub-token-shaped strings.

    ``token`` may be a plain string or a ``SecretToken``. The exact token is removed
    first, then the shapes, and the two steps repeat until neither finds anything, so
    neither can be re-formed by the other's replacement. A token that is a substring of
    the placeholder is deleted rather than replaced, so such a token also removes
    that part of the placeholder. A pure function: it never mutates its arguments and
    never raises for a ``str``.
    """
    raw = token.reveal() if isinstance(token, SecretToken) else token
    # A token that is a substring of the placeholder ("RED" inside "[REDACTED]") would
    # survive replacement, so such tokens are deleted instead.
    delete = raw is not None and raw != "" and raw in REDACTED
    while True:
        before = text
        if raw:
            text = text.replace(raw, "" if delete else REDACTED)
        text = _SECRET_SHAPES.sub(REDACTED, text)
        if text == before:
            return text
        # One step can re-form the token from its neighbours and the placeholder
        # ("0[" in "0[0[" becomes "[REDACTED]0[" ...) or put it back through the shape
        # placeholder. Repeat until a pass changes nothing, so the result holds neither.
        # Replacing can grow the text, so a token that survives a replacement pass is
        # deleted from then on; deletion only shortens the text, which ends the loop.
        if raw and not delete and raw in text:
            delete = True
