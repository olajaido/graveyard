"""``parse_install``: read the install commands out of one command line (design 4.3).

Pure and total. Segments come from ``core.install.segments.split``; each is read
with the option tables in ``profiles``. Nothing is executed, expanded or guessed:
anything not understood leaves the segment unchecked (fail open).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from core.install import npmish, pyish
from core.install.model import ParseResult, RequirementRef, Spec, Target
from core.install.profiles import (
    NPM,
    PIP,
    PNPM,
    POETRY,
    UV_ADD,
    UV_GLOBAL,
    UV_PIP,
    YARN,
    Kind,
    Profile,
    Table,
)
from core.install.segments import CONTROL_MARKER, split

MAX_TARGETS: Final = 20
MAX_REQUIREMENT_FILES: Final = 5

_ASSIGNMENT: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_WRAPPERS: Final = frozenset({"sudo", "command", "exec", "time", "nohup", "env"})
_PIP_PROG: Final = re.compile(r"pip(?:3(?:\.\d+)?)?")
_PYTHON_PROG: Final = re.compile(r"python(?:3(?:\.\d+)?)?|py")


@dataclass
class SegmentResult:
    """What one segment yielded."""

    targets: list[Target] = field(default_factory=list)
    refs: list[RequirementRef] = field(default_factory=list)
    skipped: int = 0


def _lookup(tok: str, table: Table, prefixes: tuple[str, ...]) -> tuple[Kind, str | None] | None:
    """Classify an option token: ``(kind, attached value)`` or ``None`` when unknown."""
    kind = table.get(tok)
    if kind is not None:
        return kind, None
    if tok.startswith("--"):
        name, eq, value = tok.partition("=")
        if eq:
            named = table.get(name)
            if named is not None and named is not Kind.BOOL:
                return named, value
            if any(name.startswith(p) for p in prefixes):
                return Kind.VALUE, value
        return None
    if len(tok) > 2:
        short = table.get(tok[:2])
        if short is not None and short is not Kind.BOOL:
            return short, tok[2:]
        if all(table.get("-" + c) is Kind.BOOL for c in tok[1:]):
            return Kind.BOOL, None
    return None


def _is_option(tok: str) -> bool:
    return tok.startswith("-") and len(tok) > 1


def _strip_prefix(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Drop leading assignments and at most one wrapper without options of its own."""
    i = 0
    n = len(tokens)
    while i < n and _ASSIGNMENT.match(tokens[i]):
        i += 1
    if i + 1 < n and tokens[i] in _WRAPPERS and not _is_option(tokens[i + 1]):
        i += 1
        while i < n and _ASSIGNMENT.match(tokens[i]):
            i += 1
    return tokens[i:]


def _find_verb(tokens: tuple[str, ...], start: int, profiles: tuple[Profile, ...]) -> int | None:
    """Scan global options from ``start``; return the index after an install verb, or ``None``.

    Only the first profile's global table, prefixes, name and verbs are used.
    """
    table = profiles[0].global_options
    prefixes = profiles[0].value_prefixes
    prog = profiles[0].name
    i = start
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == "--":
            return None
        if _is_option(tok):
            found = _lookup(tok, table, prefixes)
            if found is None or found[0] is Kind.REGISTRY:
                return None
            kind, attached = found
            i += 1
            if kind is not Kind.BOOL and attached is None and i < n:
                i += 1
            continue
        if prog == "yarn" and tok == "workspace":
            i += 2
            continue
        if prog == "yarn" and tok == "global":
            i += 1
            continue
        if tok in profiles[0].verbs:
            return i + 1
        return None
    return None


def _scan_arguments(tokens: tuple[str, ...], start: int, profile: Profile) -> SegmentResult | None:
    """Read options and package arguments after the verb; ``None`` = segment unchecked."""
    result = SegmentResult()
    table = profile.verb_options
    i = start
    n = len(tokens)
    only_positional = False
    poetry = profile is POETRY
    npm_family = profile in (NPM, PNPM, YARN)
    while i < n:
        tok = tokens[i]
        i += 1
        if not only_positional and tok == "--":
            only_positional = True
            continue
        if not only_positional and _is_option(tok):
            found = _lookup(tok, table, profile.value_prefixes)
            if found is None or found[0] is Kind.REGISTRY:
                return None
            kind, attached = found
            if kind is Kind.BOOL:
                continue
            value = attached
            if value is None and i < n:
                value = tokens[i]
                i += 1
            if kind is Kind.REQFILE:
                if value and value != CONTROL_MARKER:
                    result.refs.append(RequirementRef(value))
                elif value is not None:
                    result.skipped += 1
            elif kind in (Kind.CONSTRAINT, Kind.EDITABLE):
                result.skipped += 1
            continue
        target = npmish.classify(tok) if npm_family else pyish.classify(tok, poetry=poetry)
        if target is None:
            result.skipped += 1
        else:
            result.targets.append(target)
    return result


def parse_segment(tokens: tuple[str, ...]) -> SegmentResult:
    """Read one segment; an empty result when it is not a checkable install."""
    tokens = _strip_prefix(tokens)
    if not tokens:
        return SegmentResult()
    prog = tokens[0].rsplit("/", 1)[-1]
    start = 1
    verb_at: int | None = None
    profile: Profile | None = None
    if prog in ("npm", "pnpm", "yarn", "poetry"):
        profile = {"npm": NPM, "pnpm": PNPM, "yarn": YARN, "poetry": POETRY}[prog]
        verb_at = _find_verb(tokens, start, (profile,))
    elif _PIP_PROG.fullmatch(prog):
        profile = PIP
        verb_at = _find_verb(tokens, start, (PIP,))
    elif _PYTHON_PROG.fullmatch(prog):
        if len(tokens) > 2 and tokens[1] == "-m" and tokens[2] == "pip":
            profile = PIP
            verb_at = _find_verb(tokens, 3, (PIP,))
    elif prog == "uv":
        uv_top = Profile("uv", UV_ADD.verbs | {"pip"}, UV_GLOBAL, UV_GLOBAL)
        top = _find_verb(tokens, start, (uv_top,))
        if top is not None:
            if tokens[top - 1] == "add":
                profile, verb_at = UV_ADD, top
            else:
                pip_profile = Profile("uv", UV_PIP.verbs, UV_GLOBAL, UV_GLOBAL)
                verb_at = _find_verb(tokens, top, (pip_profile,))
                profile = UV_PIP
    if profile is None or verb_at is None:
        return SegmentResult()
    scanned = _scan_arguments(tokens, verb_at, profile)
    return scanned if scanned is not None else SegmentResult()


_RANK: Final = {"Pinned": 2, "Latest": 1, "Range": 0}


def _rank(spec: Spec) -> int:
    return _RANK[type(spec).__name__]


def parse_install(command: str) -> ParseResult:
    """Return the checkable packages in ``command``. Never raises for any ``str``."""
    order: list[tuple[str, str]] = []
    best: dict[tuple[str, str], Target] = {}
    refs: list[RequirementRef] = []
    skipped = 0
    truncated = False
    for segment in split(command):
        res = parse_segment(segment)
        skipped += res.skipped
        refs.extend(res.refs)
        for target in res.targets:
            key = (target.ecosystem, target.name.lower())
            current = best.get(key)
            if current is None:
                if len(order) >= MAX_TARGETS:
                    truncated = True
                    continue
                order.append(key)
                best[key] = target
            elif _rank(target.spec) > _rank(current.spec):
                best[key] = target
    return ParseResult(
        targets=tuple(best[k] for k in order),
        requirement_files=tuple(refs[:MAX_REQUIREMENT_FILES]),
        skipped=skipped,
        truncated=truncated,
    )


__all__ = [
    "MAX_REQUIREMENT_FILES",
    "MAX_TARGETS",
    "SegmentResult",
    "parse_install",
    "parse_segment",
]
