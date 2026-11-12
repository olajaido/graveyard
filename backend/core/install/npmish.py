"""Classify one npm / pnpm / yarn package argument (design 4.5, KPW-PARSE-7, KPW-PARSE-9).

Pure and total. ``classify`` returns a ``Target`` or ``None`` (skipped: counted by the caller).
Nothing is expanded or resolved.
"""

from __future__ import annotations

import re
from typing import Final

from core.install.model import Latest, Pinned, Range, Spec, Target

_FORBIDDEN: Final = frozenset("$`?[{!\x00\\")
_SKIP_PREFIXES: Final = (
    ".",
    "/",
    "~",
    "file:",
    "link:",
    "workspace:",
    "portal:",
    "patch:",
    "git+",
    "git:",
    "git@",
    "http:",
    "https:",
    "ssh:",
    "github:",
    "gitlab:",
    "bitbucket:",
    "gist:",
)
_ARCHIVES: Final = (".tgz", ".tar.gz", ".zip", ".tar")
_PRE: Final = r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
_EXACT: Final = re.compile(r"[=v]*(\d+\.\d+\.\d+" + _PRE + r")")
_LONE_LOWER: Final = re.compile(r">=?\s*v?\d+(?:\.\d+){0,2}" + _PRE)
_PARTIAL: Final = re.compile(r"[=v]*\d+(?:\.(?:\d+|[xX*])){0,2}")
_LATEST_WORDS: Final = frozenset({"", "latest", "*", "x", "X"})


def classify_spec(spec: str) -> Spec | None:
    """Return the spec class, or ``None`` for a dist-tag or anything unrecognised."""
    if spec in _LATEST_WORDS or _LONE_LOWER.fullmatch(spec):
        return Latest()
    exact = _EXACT.fullmatch(spec)
    if exact:
        return Pinned(exact.group(1))
    if spec[:1] in {"^", "~", "<", ">"} or "||" in spec or " - " in spec:
        return Range()
    if _PARTIAL.fullmatch(spec):
        return Range()
    return None


def classify(arg: str) -> Target | None:
    """Classify one package argument; ``None`` when it cannot be checked."""
    if not arg or any(ch in _FORBIDDEN for ch in arg) or arg.startswith(_SKIP_PREFIXES):
        return None
    if arg.endswith(_ARCHIVES):
        return None
    scope = arg.startswith("@")
    at = arg.find("@", 1) if scope else arg.find("@")
    name, spec = (arg, "") if at < 0 else (arg[:at], arg[at + 1 :])
    if not name or "*" in name or "?" in name:
        return None
    if not scope and "/" in name:
        return None  # user/repo shorthand
    if spec.startswith("npm:"):
        return None  # alias
    klass = classify_spec(spec)
    if klass is None:
        return None
    target = Target("npm", name, klass)
    try:
        target.purl_text(klass.version if isinstance(klass, Pinned) else None)
    except ValueError:
        return None
    return target
