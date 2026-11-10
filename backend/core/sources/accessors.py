"""Typed accessors for untrusted response content (SRC-SEC-4, SRC-API-6, SRC-HTTP-7).

Response bodies are attacker-controllable. Parsers read them only through these
functions. Each takes an ``object`` and returns either a value of the stated type or
``None``. None of them ever raises, whatever the input: wrong types, ``bool`` where an
``int`` is wanted, ``NaN``, huge integers, huge strings and unparsable dates all give
``None``.

Choices worth knowing when writing parsers:

* ``as_mapping`` accepts any ``collections.abc.Mapping`` and does **not** check the keys.
  Input comes from ``json.loads`` (SRC-HTTP-7), where every object key is a ``str``, so
  the check would only cost time. Looking up a key in the result is always safe.
* ``as_list`` accepts only ``list`` (what ``json`` produces for arrays). Tuples, sets,
  strings and mappings give ``None``.
* ``as_str`` returns the string unchanged (no stripping, no length cap). Callers that
  copy a string into evidence must validate it against a pattern first (SRC-SEC-4).
* ``as_int`` and ``as_score`` return ``None`` for a value outside the domain. Telling
  "wrong type" apart from "out of domain" (``OUT_OF_DOMAIN`` warning, SRC-API-6) is the
  caller's job: it can check ``as_X(v) is None and v is not None``.
* ``as_score`` always returns a ``float`` (``-1`` becomes ``-1.0``).
* ``as_date`` treats a timestamp without an offset as UTC and refuses strings longer
  than ``_MAX_DATE_LENGTH`` without parsing them.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Final

_MAX_DATE_LENGTH: Final = 64
"""Longest string ``as_date`` will try to parse. Real timestamps are under 40 characters."""

_SCORE_MIN: Final = 0
_SCORE_MAX: Final = 10
_SCORE_MISSING: Final = -1


def as_mapping(value: object) -> Mapping[str, object] | None:
    """Return ``value`` if it is a ``Mapping``, else ``None``. Keys are not checked."""
    if isinstance(value, Mapping):
        return value
    return None


def as_list(value: object) -> list[object] | None:
    """Return ``value`` if it is a ``list``, else ``None``."""
    if isinstance(value, list):
        return value
    return None


def as_str(value: object) -> str | None:
    """Return ``value`` if it is a ``str``, else ``None``."""
    if isinstance(value, str):
        return value
    return None


def as_bool(value: object) -> bool | None:
    """Return ``value`` if it is a ``bool``, else ``None`` (``0``/``1`` are not bools)."""
    if isinstance(value, bool):
        return value
    return None


def as_int(value: object, minimum: int = 0) -> int | None:
    """Return ``value`` if it is an ``int`` (not ``bool``, not ``float``) >= ``minimum``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < minimum:
        return None
    return value


def as_score(value: object) -> float | None:
    """Return a score as ``float`` if it is in [0, 10] or exactly -1, else ``None``.

    Accepts ``int`` and ``float``; rejects ``bool``, ``NaN`` and the infinities.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        # Compare as ints first: float(huge_int) would raise OverflowError.
        if value == _SCORE_MISSING or _SCORE_MIN <= value <= _SCORE_MAX:
            return float(value)
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value == _SCORE_MISSING or _SCORE_MIN <= value <= _SCORE_MAX:
            return value
    return None


def as_date(value: object) -> date | None:
    """Parse an ISO 8601 string into a UTC ``date``, else ``None``.

    A timestamp with an offset (``Z`` or ``+hh:mm``) is converted to UTC before the date
    is taken. A timestamp without an offset, and a date-only string, are taken as UTC.
    """
    if not isinstance(value, str) or len(value) > _MAX_DATE_LENGTH:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None
    return parsed.date()
