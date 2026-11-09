"""Purl data model, shared constants and validation (design sections 3 and 4.1).

Pure logic: no I/O, clock or environment access. Every ``Purl`` value is
canonical because ``Purl.__post_init__`` rejects anything else.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Literal, get_args

Ecosystem = Literal["npm", "pypi"]

# Formula-shape constants, not runtime configuration.
MAX_INPUT_LEN = 2048
SUPPORTED: frozenset[str] = frozenset(get_args(Ecosystem))
PEP508_NAME = re.compile(r"[A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]")  # fullmatch
PEP503_SEP = re.compile(r"[-_.]+")
QUALIFIER_KEY = re.compile(r"[a-z.\-_][a-z0-9.\-_]*")  # fullmatch; canonical lower-case key
BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
WS_OR_CTRL = re.compile(r"[\s\x00-\x1f\x7f]")
REPO_OUT = re.compile(r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")  # fullmatch
SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")  # fullmatch

_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)

_REPR_LIMIT = 100


def normalise_pypi_name(name: str) -> str:
    """PEP 503 normalisation: runs of ``-``, ``_`` and ``.`` become ``-``; lower-case."""
    return PEP503_SEP.sub("-", name).lower()


def _ascii_lower(s: str | None) -> str | None:
    """Lower-case ``A-Z`` only. Unlike ``str.lower()`` it never merges unrelated
    names (e.g. U+212A KELVIN SIGN stays as is). ``None`` passes through."""
    if s is None:
        return None
    return s.translate(_ASCII_LOWER)


def _fail(rule: str, value: object) -> ValueError:
    """Build a ValueError naming the rule and quoting the value (repr, max 100 chars)."""
    shown = repr(value)
    if len(shown) > _REPR_LIMIT:
        shown = shown[:_REPR_LIMIT] + "..."
    return ValueError(f"{rule}: {shown}")


@dataclass(frozen=True)
class Purl:
    """A canonical npm or PyPI package URL. Invalid or non-canonical values cannot exist."""

    ecosystem: Ecosystem
    namespace: str | None
    name: str
    version: str | None
    qualifiers: tuple[tuple[str, str], ...] = ()
    subpath: str | None = None

    def __post_init__(self) -> None:
        _validate(self)


def _validate(p: Purl) -> None:
    eco: object = p.ecosystem
    if not isinstance(eco, str) or eco not in SUPPORTED:
        raise _fail("PV-PURL-2 unsupported ecosystem (allowed: npm, pypi)", eco)

    for label, val in (("namespace", p.namespace), ("version", p.version)):
        if val is not None and not isinstance(val, str):
            raise _fail(f"PV-PURL-9 {label} must be str or None", val)
    if not isinstance(p.name, str):
        raise _fail("PV-PURL-9 name must be str", p.name)

    ns = p.namespace
    if eco == "npm":
        if ns is not None and (not ns.startswith("@") or len(ns) < 2 or "@" in ns[1:] or "/" in ns):
            raise _fail("PV-PURL-3 npm namespace must be '@' plus a non-empty scope", ns)
    elif ns is not None:
        raise _fail("PV-PURL-5 pypi purl must not have a namespace", ns)

    name = p.name
    if name == "":
        raise _fail("PV-PURL-3 name must not be empty", name)
    if "/" in name:
        raise _fail("PV-PURL-11 name must not contain '/'", name)
    if eco == "npm":
        if "@" in name:
            raise _fail("PV-PURL-11 npm name must not contain '@'", name)
    else:
        if name != normalise_pypi_name(name):
            raise _fail("PV-PURL-5 pypi name must be PEP 503-normalised", name)
        if not PEP508_NAME.fullmatch(name):
            raise _fail("PV-PURL-11 pypi name must match the PEP 508 name pattern", name)

    for label, val in (("namespace", ns), ("name", name), ("version", p.version)):
        if val is not None and WS_OR_CTRL.search(val):
            raise _fail(
                f"PV-PURL-11 {label} must not contain whitespace or control characters", val
            )
    if p.version == "":
        raise _fail("PV-PURL-7 version must not be empty", p.version)

    _validate_qualifiers(p.qualifiers)
    _validate_subpath(p.subpath)


def _validate_qualifiers(qualifiers: tuple[tuple[str, str], ...]) -> None:
    if not isinstance(qualifiers, tuple):
        raise _fail("PV-PURL-9 qualifiers must be a tuple", qualifiers)
    previous: str | None = None
    for item in qualifiers:
        if not isinstance(item, tuple) or len(item) != 2:
            raise _fail("PV-PURL-9 qualifier must be a (key, value) pair", item)
        key, value = item
        if not isinstance(key, str) or not isinstance(value, str):
            raise _fail("PV-PURL-9 qualifier key and value must be str", item)
        if not QUALIFIER_KEY.fullmatch(key):
            raise _fail("PV-PURL-8 qualifier key must be canonical lower-case", key)
        if previous is not None and key <= previous:
            raise _fail("PV-PURL-8 qualifiers must be sorted with unique keys", key)
        previous = key
        if value == "":
            raise _fail("PV-PURL-8 qualifier value must not be empty", item)
        if value != value.strip():
            raise _fail("PV-PURL-11 qualifier value must not have surrounding whitespace", value)


def _validate_subpath(subpath: str | None) -> None:
    if subpath is None:
        return
    if not isinstance(subpath, str):
        raise _fail("PV-PURL-9 subpath must be str or None", subpath)
    for segment in subpath.split("/"):
        if segment in ("", ".", ".."):
            raise _fail("PV-PURL-8 subpath segment must not be empty, '.' or '..'", subpath)
        if segment != segment.strip():
            raise _fail("PV-PURL-11 subpath segment must not have surrounding whitespace", subpath)
