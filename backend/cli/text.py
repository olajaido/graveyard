"""Terminal-safe text (CLI-OUT-8, D13). Pure: no I/O."""

from __future__ import annotations

import unicodedata

REPLACEMENT = "\ufffd"

# Bidirectional embeddings/overrides (U+202A-U+202E) and isolates (U+2066-U+2069).
_BIDI_CONTROLS = frozenset(
    [chr(cp) for cp in range(0x202A, 0x202F)] + [chr(cp) for cp in range(0x2066, 0x206A)]
)


def _is_forbidden(char: str) -> bool:
    # Category Cc covers C0, DEL and C1. Other format characters (e.g. ZWJ) are kept.
    return char in _BIDI_CONTROLS or unicodedata.category(char) == "Cc"


def sanitise(text: str) -> str:
    """Replace control and bidi-control characters with U+FFFD.

    Length preserving and idempotent (U+FFFD is category So, never forbidden).
    """
    return "".join(REPLACEMENT if _is_forbidden(char) else char for char in text)
