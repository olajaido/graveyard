"""Tests for ``cli.stdin.read_hook_payload`` (T8.3; KPW-TEST-10, KPW-PAY-1, KPW-PAY-2).

Real pipes (``os.pipe``) wrapped in buffered binary readers, so ``read1`` behaves as on stdin.
The HookExit-versus-``--help`` table test lands with T9.
"""

from __future__ import annotations

import contextlib
import io
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO

import pytest

from cli.stdin import read_hook_payload

PAYLOAD = '{"hook_event_name": "PreToolUse", "tool_input": {"command": "npm i x"}}'


@contextmanager
def _pipe() -> Iterator[tuple[BinaryIO, int]]:
    """A read stream and the write fd; both are closed afterwards."""
    r, w = os.pipe()
    reader = os.fdopen(r, "rb")
    try:
        yield reader, w
    finally:
        reader.close()
        with contextlib.suppress(OSError):
            os.close(w)  # may already be closed by the test


def _write(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def test_closed_pipe_returns_the_payload() -> None:
    with _pipe() as (reader, w):
        _write(w, PAYLOAD.encode())
        os.close(w)
        assert read_hook_payload(reader) == PAYLOAD


def test_never_closed_pipe_returns_the_payload_without_waiting() -> None:
    with _pipe() as (reader, w):
        _write(w, PAYLOAD.encode())
        start = time.monotonic()
        assert read_hook_payload(reader, timeout=5.0) == PAYLOAD
        assert time.monotonic() - start < 2.0


def test_never_written_pipe_returns_none_after_the_deadline() -> None:
    with _pipe() as (reader, w):
        start = time.monotonic()
        assert read_hook_payload(reader, timeout=0.2) is None
        elapsed = time.monotonic() - start
        assert 0.15 <= elapsed < 1.5
        os.close(w)  # lets the abandoned daemon thread finish


def test_eof_without_a_complete_object_returns_none() -> None:
    with _pipe() as (reader, w):
        _write(w, b'{"a": ')
        os.close(w)
        assert read_hook_payload(reader) is None
    with _pipe() as (reader, w):
        os.close(w)
        assert read_hook_payload(reader) is None


def test_non_object_json_returns_none() -> None:
    with _pipe() as (reader, w):
        _write(w, b"[1, 2]")
        os.close(w)
        assert read_hook_payload(reader) is None


def test_more_than_one_mebibyte_returns_none() -> None:
    big = b'{"pad": "' + b"x" * ((1 << 20) + 10) + b'"}'
    with _pipe() as (reader, w):
        writer = threading.Thread(target=lambda: _safe_write_close(w, big), daemon=True)
        writer.start()
        assert read_hook_payload(reader, timeout=10.0) is None
        writer.join(5.0)


def _safe_write_close(fd: int, data: bytes) -> None:
    with contextlib.suppress(OSError):  # the reader gave up and closed its end
        _write(fd, data)
        os.close(fd)


def test_just_under_the_limit_is_accepted() -> None:
    body = '{"pad": "' + "x" * 200 + '"}'
    with _pipe() as (reader, w):
        _write(w, body.encode())
        os.close(w)
        assert read_hook_payload(reader, limit=len(body.encode())) == body
    with _pipe() as (reader, w):
        _write(w, body.encode())
        os.close(w)
        assert read_hook_payload(reader, limit=len(body.encode()) - 1) is None


class _Tty(io.BytesIO):
    def isatty(self) -> bool:
        return True

    def read1(self, size: int | None = -1) -> bytes:
        raise AssertionError("a terminal must not be read")


def test_terminal_like_stream_returns_none_without_reading() -> None:
    assert read_hook_payload(_Tty(PAYLOAD.encode())) is None


def test_no_stream_returns_none() -> None:
    assert read_hook_payload(None) is None


def test_invalid_utf8_is_replaced_not_raised() -> None:
    raw = b'{"command": "a\xff\xfeb"}'
    with _pipe() as (reader, w):
        _write(w, raw)
        os.close(w)
        out = read_hook_payload(reader)
    assert out == '{"command": "a\ufffd\ufffdb"}'


def test_payload_split_across_two_writes() -> None:
    with _pipe() as (reader, w):
        _write(w, PAYLOAD.encode()[:20])

        def second() -> None:
            time.sleep(0.1)
            _write(w, PAYLOAD.encode()[20:])  # pipe left open

        t = threading.Thread(target=second, daemon=True)
        t.start()
        assert read_hook_payload(reader, timeout=5.0) == PAYLOAD
        t.join(2.0)


def test_multibyte_character_split_across_two_writes() -> None:
    raw = '{"name": "é€😀"}'.encode()
    cut = raw.index("€".encode()) + 1  # in the middle of a 3-byte sequence
    with _pipe() as (reader, w):
        _write(w, raw[:cut])

        def second() -> None:
            time.sleep(0.1)
            _write(w, raw[cut:])

        t = threading.Thread(target=second, daemon=True)
        t.start()
        assert read_hook_payload(reader, timeout=5.0) == '{"name": "é€😀"}'
        t.join(2.0)


def test_closed_stream_returns_none() -> None:
    stream = io.BytesIO(b"{}")
    stream.close()
    assert read_hook_payload(stream) is None


@pytest.mark.parametrize("text", ["{}", '  \n{"a": {"b": [1]}}\n'])
def test_leading_whitespace_and_trailing_newline(text: str) -> None:
    with _pipe() as (reader, w):
        _write(w, text.encode())
        os.close(w)
        assert read_hook_payload(reader) == text
