"""Scope parser for ``requirements.txt`` (design §6.4, DG-SCP-0, DG-SCP-8).

Every pinned requirement (``name==version`` or ``name===version``) is ``runtime``
in both ``package_scopes`` and ``direct_scopes``: the format cannot say which
entries are direct. Unpinned, ranged, URL and path lines become
``REQUIREMENT_SKIPPED`` warnings; blanks, comments and option lines are skipped
silently. Parsing is a single linear pass and the only regex is anchored with no
nested quantifiers. Pure: no I/O, no logging.
"""

from __future__ import annotations

import re
from typing import Final

from core.graph.diagnostics import make_warning
from core.graph.keys import pypi_key
from core.graph.model import GraphWarning, Scope, ScopeResult
from core.graph.scopes_common import check_size, result

_BOM: Final = "\ufeff"
_PIN: Final = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(===|==)\s*([^\s,;*]+)")
_COMMENT: Final = re.compile(r"(?:^|\s)#")  # '#' at line start or after whitespace
_OPTION: Final = re.compile(r"\s--")  # start of trailing options such as --hash=...
_RUNTIME: Final[Scope] = "runtime"


def _join_continuations(text: str) -> list[str]:
    """Split into logical lines, joining a line that ends in an unescaped ``\\``.

    A comment-only line never continues onto the next line. Linear in ``len(text)``.
    """
    logical: list[str] = []
    parts: list[str] = []
    for raw in text.splitlines():
        trailing = len(raw) - len(raw.rstrip("\\"))
        continued = trailing % 2 == 1 and not raw.lstrip().startswith("#")
        if continued:
            parts.append(raw[:-1])
            continue
        parts.append(raw)
        logical.append(" ".join(parts) if len(parts) > 1 else raw)
        parts = []
    if parts:  # input ended on a continuation
        logical.append(" ".join(parts))
    return logical


def _skipped(line: str, reason: str) -> GraphWarning:
    """Build the ``REQUIREMENT_SKIPPED`` warning for ``line``."""
    return make_warning("REQUIREMENT_SKIPPED", f"requirement skipped: {reason}", None, (line,))


def parse_requirements_txt(text: str) -> ScopeResult:
    """Parse ``requirements.txt`` text into runtime scopes for its pinned lines.

    Raises ``ValueError`` only when the text exceeds ``MAX_LOCKFILE_CHARS``
    (DG-SCP-0). For any other ``str``, including lone surrogates, it returns.
    """
    check_size(text)
    if text.startswith(_BOM):
        text = text[1:]

    warnings: list[GraphWarning] = []
    scopes: dict[str, Scope] = {}
    for logical in _join_continuations(text):
        line = logical.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        comment = _COMMENT.search(line)
        if comment:
            line = line[: comment.start()].strip()
        option = _OPTION.search(line)
        if option:
            line = line[: option.start()].strip()
        if not line:
            continue
        if "://" in line or line.startswith((".", "/")):
            warnings.append(_skipped(line, "URL or path requirement"))
            continue
        spec = line.split(";", 1)[0].strip()  # drop the environment marker
        match = _PIN.fullmatch(spec)
        if match is None:
            warnings.append(_skipped(line, "not pinned with == or ==="))
            continue
        try:
            key = pypi_key(match.group(1), match.group(4))
        except ValueError:
            warnings.append(
                make_warning(
                    "LOCKFILE_ENTRY_SKIPPED",
                    "requirement name or version cannot form a valid package URL",
                    None,
                    (line,),
                )
            )
            continue
        scopes[key] = _RUNTIME
    return result(scopes, scopes, warnings)
