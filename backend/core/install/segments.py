"""Split a shell command line into segments of word tokens (design 4.2).

Pure and total: ``split`` never raises. A small quote-aware scanner finds the
unquoted operators (``shlex`` with ``punctuation_chars`` cannot tell a quoted
``;`` from an operator), and ``shlex.split`` is the only tokeniser of the text
between them. Nothing is expanded.
"""

from __future__ import annotations

import re
import shlex
from typing import Final

CONTROL_MARKER: Final = "\x00"

_BOUNDARY: Final = frozenset(";&|\n")
_TRAILING_FD: Final = re.compile(r"(?:^|[ \t])[0-9]+$")


def _mark_control(token: str) -> str:
    """Replace a token with a control character by the skip marker."""
    for ch in token:
        if (ord(ch) < 32 and ch != "\t") or ch == "\x7f":
            return CONTROL_MARKER
    return token


def _words(run: str, *, drop_fd: bool) -> list[str] | None:
    """Tokenise ``run`` with ``shlex``; ``None`` on ``ValueError``."""
    try:
        words = shlex.split(run, comments=False, posix=True)
    except ValueError:
        return None
    if drop_fd and words and _TRAILING_FD.search(run):
        words.pop()
    return [_mark_control(w) for w in words]


def split(command: str) -> tuple[tuple[str, ...], ...]:
    """Return one tuple of word tokens per executable segment; ``()`` when unusable."""
    if not isinstance(command, str):
        return ()
    segments: list[tuple[str, ...]] = []
    words: list[str] = []
    cur: list[str] = []
    poisoned = False
    redirected = False

    def flush_run(*, drop_fd: bool) -> bool:
        nonlocal cur
        run = "".join(cur)
        cur = []
        if redirected:
            return True
        found = _words(run, drop_fd=drop_fd)
        if found is None:
            return False
        words.extend(found)
        return True

    def end_segment() -> bool:
        nonlocal words, poisoned, redirected
        if not flush_run(drop_fd=False):
            return False
        if words and not poisoned:
            segments.append(tuple(words))
        words, poisoned, redirected = [], False, False
        return True

    n = len(command)
    i = 0
    word_start = True  # at the start of a word (a '#' here begins a comment)
    while i < n:
        ch = command[i]
        if ch == "\\":
            if i + 1 >= n:
                return ()
            cur.append(command[i : i + 2])
            i += 2
            word_start = False
        elif ch == "'":
            end = command.find("'", i + 1)
            if end < 0:
                return ()
            cur.append(command[i : end + 1])
            i = end + 1
            word_start = False
        elif ch == '"':
            j = i + 1
            while j < n and command[j] != '"':
                j += 2 if command[j] == "\\" else 1
            if j >= n:
                return ()
            cur.append(command[i : j + 1])
            i = j + 1
            word_start = False
        elif ch == "#" and word_start:
            end = command.find("\n", i)
            i = n if end < 0 else end
        elif ch in " \t\r":
            cur.append(ch)
            i += 1
            word_start = True
        elif ch in "()":
            poisoned = True
            if not flush_run(drop_fd=False):
                return ()
            i += 1
            word_start = True
        elif ch in "<>" or (ch == "&" and command.startswith("&>", i)):
            if command.startswith("<<", i):
                poisoned = True
            if not flush_run(drop_fd=True):
                return ()
            redirected = True
            i += 1
            while i < n and command[i] in "<>&" and not command.startswith("&&", i):
                i += 1
            word_start = True
        elif ch in _BOUNDARY:
            if not end_segment():
                return ()
            i += 1
            word_start = True
        else:
            cur.append(ch)
            i += 1
            word_start = False
    if not end_segment():
        return ()
    return tuple(segments)
