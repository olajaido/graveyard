"""Purl parsing, formatting and normalisation (design sections 4.2 and 4.3).

Wraps ``packageurl-python`` for grammar and decoding, then applies our
ecosystem rules. Only ``ValueError`` escapes from the public functions; other
exceptions are chained with ``raise ... from exc``.

``format_purl`` never uses ``PackageURL.to_string()``: the library lower-cases
npm names (D3), which we must preserve.

``package_key`` is the key for EX-7 dedupe and the AU-5 autopsy cache; it must
not be used where the registry name is needed (use ``registry_name``).
"""

from __future__ import annotations

import dataclasses
import string
from typing import cast

from packageurl import PackageURL, normalize_qualifiers, normalize_subpath, quote, unquote

from core.purl.model import (
    BAD_ESCAPE,
    MAX_INPUT_LEN,
    PEP508_NAME,
    SUPPORTED,
    WS_OR_CTRL,
    Ecosystem,
    Purl,
    _fail,
    normalise_pypi_name,
)

__all__ = [
    "format_purl",
    "normalise_purl",
    "normalise_pypi_name",
    "package_key",
    "parse_purl",
    "registry_name",
]

_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def _ascii_lower(s: str | None) -> str | None:
    """Lower-case A-Z only (not ``str.lower()``); ``None`` passes through."""
    return None if s is None else s.translate(_ASCII_LOWER)


def _guard(s: object) -> str:
    """Run every check that must happen before the library is called."""
    if not isinstance(s, str):
        raise _fail("PV-PURL-13 purl must be a str", s)
    if len(s) > MAX_INPUT_LEN:
        raise _fail(f"PV-PURL-12 purl longer than {MAX_INPUT_LEN} characters", s)
    try:
        s.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _fail("PV-PURL-13 purl is not encodable as UTF-8", s) from exc
    if WS_OR_CTRL.search(s):
        raise _fail("PV-PURL-11 purl contains whitespace or control characters", s)
    if BAD_ESCAPE.search(s):
        raise _fail("PV-PURL-11 purl contains a malformed percent-escape", s)

    head, _, _subpath = s.partition("#")
    head, _, quals_raw = head.partition("?")
    if head.endswith("@"):
        raise _fail("PV-PURL-7 version is empty after '@'", s)
    if quals_raw:
        keys = [
            part.partition("=")[0].strip().lower() for part in quals_raw.split("&") if part != ""
        ]
        if len(keys) != len(set(keys)):
            raise _fail("PV-PURL-8 duplicate qualifier key", s)
    return s


def parse_purl(s: str) -> Purl:
    """Parse ``s`` into a canonical ``Purl``. Raises ``ValueError`` and nothing else."""
    _guard(s)
    try:
        return _parse(s)
    except ValueError:
        raise
    except Exception as exc:
        raise _fail(f"PV-PURL-13 purl could not be parsed ({type(exc).__name__})", s) from exc


def _parse(s: str) -> Purl:
    norm = PackageURL.from_string(s)
    raw = PackageURL.from_string(s, normalize_purl=False)

    eco = norm.type.lower()
    if eco not in SUPPORTED:
        raise _fail("PV-PURL-2 unsupported ecosystem (allowed: npm, pypi)", norm.type)
    ecosystem = cast("Ecosystem", eco)

    raw_name = unquote(raw.name)
    if ecosystem == "npm":
        name = raw_name
        if name.lower() != norm.name.lower():
            raise _fail("PV-PURL-4 npm name disagrees between parses", s)
    else:
        if not PEP508_NAME.fullmatch(raw_name):
            raise _fail("PV-PURL-11 pypi name must match the PEP 508 name pattern", raw_name)
        name = normalise_pypi_name(raw_name)

    qualifiers = norm.qualifiers
    if not isinstance(qualifiers, dict):
        raise _fail("PV-PURL-8 qualifiers could not be decoded", s)

    return Purl(
        ecosystem=ecosystem,
        namespace=norm.namespace,
        name=name,
        version=norm.version,
        qualifiers=tuple(sorted(qualifiers.items())),
        subpath=norm.subpath,
    )


def format_purl(p: Purl) -> str:
    """Return the canonical purl string for ``p`` (never via ``to_string()``)."""
    try:
        out = f"pkg:{p.ecosystem}/"
        if p.namespace:
            out += quote(p.namespace) + "/"
        out += quote(p.name)
        if p.version is not None:
            out += "@" + quote(p.version)
        if p.qualifiers:
            encoded = normalize_qualifiers(dict(p.qualifiers), encode=True)
            if not isinstance(encoded, str):
                raise _fail("PV-PURL-8 qualifiers could not be encoded", p.qualifiers)
            out += "?" + encoded
        if p.subpath:
            sub = normalize_subpath(p.subpath, encode=True)
            if sub is None:
                raise _fail("PV-PURL-8 subpath could not be encoded", p.subpath)
            out += "#" + sub
    except UnicodeEncodeError as exc:
        raise _fail("PV-PURL-13 purl component is not encodable as UTF-8", p) from exc
    return out


def normalise_purl(s: str) -> str:
    """Return the canonical purl string for the purl denoted by ``s``."""
    return format_purl(parse_purl(s))


def package_key(p: Purl) -> str:
    """Return the package key: the canonical purl minus ``pkg:``, qualifiers and subpath.

    This is the key for EX-7 dedupe and the AU-5 autopsy cache. For npm the
    namespace and name are ASCII-lower-cased; pypi is unchanged (already PEP 503
    normalised). The version is never folded. It must not be used where the
    registry name is needed (use ``registry_name``), because case is lost.
    """
    k = dataclasses.replace(p, qualifiers=(), subpath=None)
    if p.ecosystem == "npm":
        k = dataclasses.replace(
            k, namespace=_ascii_lower(p.namespace), name=cast("str", _ascii_lower(p.name))
        )
    return format_purl(k).removeprefix("pkg:")


def registry_name(p: Purl) -> str:
    """Return the decoded registry name (``@scope/name`` or ``name``), case preserved."""
    return f"{p.namespace}/{p.name}" if p.namespace else p.name
