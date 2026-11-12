"""Classify one pip / uv / poetry package argument, PEP 508 style (design 4.5, KPW-PARSE-10).

Pure and total. ``classify`` returns a ``Target`` or ``None`` (skipped: counted by the caller).
"""

from __future__ import annotations

import re
from typing import Final

from core.install.model import Latest, Pinned, Range, Spec, Target
from core.purl import normalise_pypi_name

_FORBIDDEN: Final = frozenset("$`?{\x00")
_ARCHIVES: Final = (".whl", ".tar.gz", ".zip", ".tgz", ".tar")
_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_EXTRAS: Final = re.compile(r"\s*\[[A-Za-z0-9._,\s-]*\]")
_VER: Final = r"[0-9A-Za-z][0-9A-Za-z.+_-]*"
_LONE_LOWER: Final = re.compile(r">=?(" + _VER + ")")
_PINNED: Final = re.compile(r"===?(" + _VER + ")")
_CLAUSE: Final = r"(?:===?|~=|!=|<=?|>=?)[0-9A-Za-z.*+_-]+"
_RANGE: Final = re.compile(_CLAUSE + r"(?:," + _CLAUSE + r")*")
_EXACT_WORD: Final = re.compile(r"\d+(?:\.\d+)*(?:[-+.]?[0-9A-Za-z.+_-]+)?")
_LATEST_WORDS: Final = frozenset({"latest", "*"})
_BAD_BANG: Final = re.compile(r"!(?!=)")
_BAD_STAR: Final = re.compile(r"(?<!\.)\*")


def classify_specifier(spec: str) -> Spec | None:
    """Classify a PEP 440 specifier string (whitespace already removed)."""
    if spec == "":
        return Latest()
    if _LONE_LOWER.fullmatch(spec):
        return Latest()
    pinned = _PINNED.fullmatch(spec)
    if pinned:
        return Pinned(pinned.group(1))
    if _RANGE.fullmatch(spec) and not _BAD_STAR.search(spec):
        return Range()
    return None


def _poetry_spec(text: str) -> Spec | None:
    if text in _LATEST_WORDS:
        return Latest()
    if text[:1] in {"^", "~"} and text[:2] != "~=":
        return Range()
    if _EXACT_WORD.fullmatch(text):
        return Pinned(text)
    return classify_specifier(text)


def classify(arg: str, *, poetry: bool = False) -> Target | None:
    """Classify one package argument; ``None`` when it cannot be checked."""
    if not arg or any(ch in _FORBIDDEN for ch in arg) or arg.startswith(("~", ".", "/")):
        return None
    if "://" in arg or " @ " in arg or arg.startswith(("git+", "hg+", "svn+", "bzr+")):
        return None
    req = arg.split(";", 1)[0].strip()
    if "/" in req or "\\" in req or req.endswith(_ARCHIVES) or _BAD_BANG.search(req):
        return None
    m = _NAME.match(req)
    if m is None:
        return None
    name = m.group(0)
    rest = req[m.end() :]
    extras = _EXTRAS.match(rest)
    if extras:
        rest = rest[extras.end() :]
    elif rest.lstrip().startswith("["):
        return None
    rest = re.sub(r"\s+", "", rest)
    klass: Spec | None
    if rest.startswith("@"):
        klass = _poetry_spec(rest[1:]) if poetry and len(rest) > 1 else None
    else:
        klass = classify_specifier(rest)
    if klass is None:
        return None
    target = Target("pypi", normalise_pypi_name(name), klass)
    try:
        target.purl_text(klass.version if isinstance(klass, Pinned) else None)
    except ValueError:
        return None
    return target
