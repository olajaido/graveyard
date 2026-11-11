"""Fixed versions of an OSV advisory for one package (SRC-OSV-4, D17, design §6.1).

``fixed_versions(vuln, ecosystem, name)`` walks ``vuln["affected"]`` and returns the sorted,
unique ``fixed`` event versions of the entries that name the queried package, or ``None`` when
the advisory cannot be read (below). ``has_fix`` is ``bool(fixed_versions(...))`` or ``None``.

Which entries name the package
    * ``package.ecosystem`` equals ``ecosystem`` exactly and ``package.name`` equals ``name``
      after PEP 503 normalisation (applied to both ecosystems, as the prototype does): the entry
      is **ours**;
    * a well-typed ``ecosystem`` or ``name`` that differs: the entry is **another package** and
      is ignored, whatever else it holds, however damaged;
    * ``package`` absent or ``null``, or ``ecosystem`` / ``name`` absent or ``null``: the entry
      has no (complete) identity, so it names nobody and is ignored (an absence, D17).

What is unreadable (D17: absent or ``null`` is an absence, wrong-typed is not)
    The whole advisory is unreadable, and the result is ``None``, when any of these is present
    with the wrong type:

    * ``affected`` is not a list, or an element of it is not an object;
    * ``package`` is not an object, or ``ecosystem`` / ``name`` is not a string, **and nothing
      proves the entry is another package** (for example ``name`` is damaged but ``ecosystem``
      says ``Go``: that entry is not ours and is ignored; ``name`` damaged and ``ecosystem``
      ``npm``: it might be ours, so it is unreadable);
    * in an entry that is ours: ``ranges`` is not a list, a range is not an object, a range
      ``type`` is not a string, ``events`` is not a list, an event is not an object, an
      event's ``introduced`` is not a string, or an event's ``fixed`` is not a string or is a
      string that fails ``is_valid_version`` (SRC-SEC-4: empty, spaces, ``;``, over 100
      characters).

    Why fail closed: a ``fixed`` that stops being a usable version would otherwise turn a
    fixable advisory into a no-fix one, which flips Wounded into Cursed with no warning. The
    caller makes the package's S7 ``None`` with ``UNEXPECTED_SHAPE`` (SRC-OSV-6).

Ranges
    A range of type ``GIT`` keeps its own rule: it is skipped without looking inside (its
    ``fixed`` values are commit hashes and its ``events`` may be anything). A range with an
    absent or ``null`` ``type`` is read like a non-``GIT`` range. A ``fixed`` counts only if it
    is a ``str`` that passes ``is_valid_version`` (SRC-SEC-4); anything else makes the advisory
    unreadable. ``last_affected`` and ``limit`` are not read.

The advisory is untrusted (SRC-SEC-4). It is read with plain ``isinstance`` checks, nothing
here raises, and the argument is not mutated.

Ported from the prototype's ``osv_fixed_versions`` (``scripts/capture_anchors.py``) with
explicit type checks.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from core.purl import normalise_pypi_name
from core.sources.facts import is_valid_version

_OURS: Final = "ours"
_OTHER: Final = "other"
_UNREADABLE: Final = "unreadable"


def fixed_versions(vuln: object, ecosystem: str, name: str) -> tuple[str, ...] | None:
    """Sorted, unique, valid ``fixed`` versions for the package; ``None`` if unreadable."""
    if not isinstance(vuln, Mapping):
        return None
    affected = vuln.get("affected")
    if affected is None:
        return ()
    if not isinstance(affected, list):
        return None
    wanted = normalise_pypi_name(name)
    found: set[str] = set()
    for entry in affected:
        if not isinstance(entry, Mapping):
            return None
        verdict = _whose(entry, ecosystem, wanted)
        if verdict == _UNREADABLE:
            return None
        if verdict == _OTHER:
            continue
        fixes = _range_fixes(entry.get("ranges"))
        if fixes is None:
            return None
        found.update(fixes)
    return tuple(sorted(found))


def has_fix(vuln: object, ecosystem: str, name: str) -> bool | None:
    """True iff a valid fixed version exists, ``False`` if none, ``None`` if unreadable."""
    fixed = fixed_versions(vuln, ecosystem, name)
    return None if fixed is None else bool(fixed)


def _whose(entry: Mapping[str, object], ecosystem: str, wanted: str) -> str:
    """Whether ``entry`` is ours, another package's, or cannot be told apart (see module doc)."""
    raw = entry.get("package")
    if raw is None:
        return _OTHER
    if not isinstance(raw, Mapping):
        return _UNREADABLE
    eco, pkg_name = raw.get("ecosystem"), raw.get("name")
    # Provably another package: a well-typed identity field that differs.
    if isinstance(eco, str) and eco != ecosystem:
        return _OTHER
    if isinstance(pkg_name, str) and normalise_pypi_name(pkg_name) != wanted:
        return _OTHER
    if (eco is not None and not isinstance(eco, str)) or (
        pkg_name is not None and not isinstance(pkg_name, str)
    ):
        return _UNREADABLE  # damaged, and nothing says it is not ours
    if eco is None or pkg_name is None:
        return _OTHER  # an incomplete identity names nobody
    return _OURS


def _range_fixes(ranges: object) -> set[str] | None:
    """Valid ``fixed`` strings in the non-``GIT`` ranges of one entry; ``None`` if unreadable."""
    out: set[str] = set()
    if ranges is None:
        return out
    if not isinstance(ranges, list):
        return None
    for item in ranges:
        if not isinstance(item, Mapping):
            return None
        range_type = item.get("type")
        if range_type is not None and not isinstance(range_type, str):
            return None
        if range_type == "GIT":
            continue
        events = item.get("events")
        if events is None:
            continue
        if not isinstance(events, list):
            return None
        for event in events:
            if not isinstance(event, Mapping):
                return None
            introduced = event.get("introduced")
            if introduced is not None and not isinstance(introduced, str):
                return None
            fixed = event.get("fixed")
            if fixed is None:
                continue
            if not isinstance(fixed, str) or not is_valid_version(fixed):
                return None  # a wrong type and a string outside the pattern are both unreadable
            out.add(fixed)
    return out
