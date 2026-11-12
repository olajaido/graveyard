"""Bounded read of the hook payload from stdin (KPW-PAY-1, KPW-PAY-2, design §5.2).

The read runs in a daemon thread so a stream that never closes cannot block the caller or keep
the process alive. This is the only module that may import ``threading``.
"""

from __future__ import annotations

import codecs
import json
import threading
from typing import BinaryIO, Final

__all__ = ["read_hook_payload"]

_CHUNK: Final = 65_536


def read_hook_payload(
    stream: BinaryIO | None, *, limit: int = 1 << 20, timeout: float = 2.0
) -> str | None:
    """Return stdin text holding one complete JSON object, or ``None``.

    ``None`` when there is no stream, it is a terminal, the read times out, overflows ``limit``
    characters of input, fails, or ends without a complete JSON object.
    """
    if stream is None:
        return None
    try:
        if stream.isatty():
            return None
    except (OSError, ValueError):
        return None

    done = threading.Event()
    result: list[str] = []

    def work() -> None:
        try:
            _pump(stream, limit, result)
        except (OSError, ValueError, RecursionError):
            result.clear()
        finally:
            done.set()

    threading.Thread(target=work, name="graveyard-stdin", daemon=True).start()
    if not done.wait(timeout):
        return None
    return result[0] if result else None


def _pump(stream: BinaryIO, limit: int, result: list[str]) -> None:
    """Read chunks until a complete JSON object, EOF or overflow; append the text on success."""
    read = getattr(stream, "read1", None) or stream.read
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    json_decoder = json.JSONDecoder()
    parts: list[str] = []
    received = 0
    while True:
        chunk = read(_CHUNK)
        if not chunk:
            parts.append(decoder.decode(b"", final=True))
            text = "".join(parts)
            if _is_object(json_decoder, text):
                result.append(text)
            return
        received += len(chunk)
        if received > limit:
            return
        parts.append(decoder.decode(chunk))
        text = "".join(parts)
        if _is_object(json_decoder, text):
            result.append(text)
            return


def _is_object(decoder: json.JSONDecoder, text: str) -> bool:
    try:
        value, _ = decoder.raw_decode(text.lstrip())
    except ValueError:
        return False
    return isinstance(value, dict)
