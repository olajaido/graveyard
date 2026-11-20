"""Scan IDs (SB-API-2): a ULID, ``-``, and 64 random bits as 16 hex characters."""

from __future__ import annotations

import re
from typing import Final

_CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SCAN_ID_RE: Final = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}-[0-9a-f]{16}$")
_MAX_TIME_MS: Final = (1 << 48) - 1


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_scan_id(now_ms: int, rand10: bytes, rand8: bytes) -> str:
    """Build a scan ID from a millisecond timestamp and caller-supplied random bytes."""
    if not 0 <= now_ms <= _MAX_TIME_MS:
        raise ValueError("now_ms out of range")
    if len(rand10) != 10 or len(rand8) != 8:
        raise ValueError("need 10 and 8 random bytes")
    ulid = _encode(now_ms, 10) + _encode(int.from_bytes(rand10, "big"), 16)
    return f"{ulid}-{rand8.hex()}"


def is_scan_id(text: object) -> bool:
    return isinstance(text, str) and SCAN_ID_RE.fullmatch(text) is not None
