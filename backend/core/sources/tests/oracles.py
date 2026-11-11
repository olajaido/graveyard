"""Independent oracles for the ``core.sources`` property tests.

``has_fix_oracle`` (SRC-TEST-3, design §6.1) answers the same question as
``core.sources.osv_fix.has_fix`` by a different method (``True``, ``False``, or ``None`` for an
advisory that cannot be read, D17). Instead of looking keys up level
by level, it flattens the whole document into ``(path, value)`` pairs and then asks
"does a path of this shape exist?". A guard that one implementation forgets, such as a
missing ``type`` or a wrongly typed ``package``, then shows up as a counterexample.

This module must stay independent of the code it checks. It imports only the standard
library, repeats the version pattern (SRC-SEC-4) and the PEP 503 normaliser instead of
importing them, and ``test_oracles_independence.py`` enforces that with ``ast``.

``s1_oracle`` and ``s1b_oracle`` (SRC-TEST-9) do the same for the Kleene signals of
``core.sources.assemble``: they enumerate completions instead of using ``k_and`` / ``k_or``.
The Resting-candidate oracle (SRC-TEST-15) needs ``score_package``, so it lives in
``test_properties_resting.py``.
"""

from __future__ import annotations

import re

Path = tuple[str | int, ...]
"""Keys (``str``) and list positions (``int``) from the document root to a value."""

_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!~-]{0,99}")
_SEPARATOR_RUN = re.compile(r"[-_.]+")


def _normalise(name: str) -> str:
    """PEP 503 name normalisation."""
    return _SEPARATOR_RUN.sub("-", name).lower()


def flatten_pairs(doc: object) -> list[tuple[Path, object]]:
    """Every node of ``doc`` as ``(path, value)``, containers included, root first.

    Walks with an explicit stack. Only ``dict`` and ``list`` are containers. A dict entry
    whose key is not a ``str`` is dropped: JSON object keys are always strings.
    """
    pairs: list[tuple[Path, object]] = []
    stack: list[tuple[Path, object]] = [((), doc)]
    while stack:
        path, value = stack.pop()
        pairs.append((path, value))
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key, str):
                    stack.append(((*path, key), child))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                stack.append(((*path, index), child))
    return pairs


def _children(flat: dict[Path, object], path: Path) -> list[int]:
    """List positions below ``path``, in order, read off the flattened pairs."""
    return sorted(
        step[-1]
        for step in flat
        if len(step) == len(path) + 1 and step[: len(path)] == path and isinstance(step[-1], int)
    )


def _whose(flat: dict[Path, object], entry: Path, ecosystem: str, wanted: str) -> str:
    """``"ours"``, ``"other"`` or ``"unreadable"`` for the ``affected`` entry at ``entry``."""
    package = (*entry, "package")
    value = flat.get(package)  # a missing key and a null both read as None
    if value is None:
        return "other"
    if not isinstance(value, dict):
        return "unreadable"
    eco = flat.get((*package, "ecosystem"))
    name = flat.get((*package, "name"))
    if isinstance(eco, str) and eco != ecosystem:
        return "other"  # provably another package
    if isinstance(name, str) and _normalise(name) != wanted:
        return "other"
    if (eco is not None and not isinstance(eco, str)) or (
        name is not None and not isinstance(name, str)
    ):
        return "unreadable"  # damaged, and nothing says it is not ours
    if eco is None or name is None:
        return "other"  # an incomplete identity names nobody
    return "ours"


def has_fix_oracle(doc: object, ecosystem: str, name: str) -> bool | None:
    """Whether ``doc`` has a valid ``fixed`` event for the package; ``None`` if unreadable.

    The advisory is **unreadable** (D17) when, anywhere, a value is present and of the wrong
    type in a place that could change the answer for this package: ``doc`` itself, ``affected``
    or one of its elements; an entry's ``package`` or its ``ecosystem`` / ``name`` unless the
    other one proves the entry is another package; and, in an entry that names the package,
    ``ranges``, a range, a range ``type``, ``events``, an event, ``introduced``, or a ``fixed``
    that is not a string matching the version pattern in full.
    A ``GIT`` range is skipped without looking inside. ``null`` or absent is never wrong-typed.

    Otherwise the answer is ``True`` iff some event of a non-``GIT`` range of an entry that
    names the package has a ``fixed`` (an absent or ``null`` ``type`` counts as not ``GIT``).
    All entries are checked before an answer is given, so damage anywhere makes the whole
    answer ``None``.
    """
    if not isinstance(doc, dict):
        return None
    flat = dict(flatten_pairs(doc))
    affected = flat.get(("affected",))
    if affected is None:
        return False
    if not isinstance(affected, list):
        return None
    wanted = _normalise(name)
    found = False
    for i in _children(flat, ("affected",)):
        entry = ("affected", i)
        if not isinstance(flat[entry], dict):
            return None
        verdict = _whose(flat, entry, ecosystem, wanted)
        if verdict == "unreadable":
            return None
        if verdict == "other":
            continue
        ranges = flat.get((*entry, "ranges"))
        if ranges is None:
            continue
        if not isinstance(ranges, list):
            return None
        for j in _children(flat, (*entry, "ranges")):
            rng = (*entry, "ranges", j)
            if not isinstance(flat[rng], dict):
                return None
            range_type = flat.get((*rng, "type"))
            if range_type is not None and not isinstance(range_type, str):
                return None
            if range_type == "GIT":
                continue
            events = flat.get((*rng, "events"))
            if events is None:
                continue
            if not isinstance(events, list):
                return None
            for k in _children(flat, (*rng, "events")):
                event = (*rng, "events", k)
                if not isinstance(flat[event], dict):
                    return None
                introduced = flat.get((*event, "introduced"))
                if introduced is not None and not isinstance(introduced, str):
                    return None
                fixed = flat.get((*event, "fixed"))
                if fixed is None:
                    continue
                if not isinstance(fixed, str) or _VERSION.fullmatch(fixed) is None:
                    return None
                found = True
    return found


# --- Kleene logic (SRC-TEST-9, design §9.1) ---------------------------------------------------
#
# S1 and S1b are three-valued. The oracle does not use any three-valued operator. It fills
# every unknown (``None``) part with each of ``True`` and ``False``, evaluates the plain
# two-valued formula for every filling, and reports a value only if all fillings agree.


def _fillings(parts: list[bool | None]) -> list[list[bool]]:
    """Every way to replace the ``None`` entries of ``parts`` by a ``bool``."""
    if not parts:
        return [[]]
    head, rest = parts[0], _fillings(parts[1:])
    options = [True, False] if head is None else [head]
    return [[option, *tail] for option in options for tail in rest]


def _agreed(outcomes: list[bool]) -> bool | None:
    """``True`` / ``False`` if every outcome is that value, else ``None`` (unknown)."""
    if all(outcomes):
        return True
    if not any(outcomes):
        return False
    return None


def s1_oracle(ecosystem: str, latest_deprecated: bool | None, archived: bool | None) -> bool | None:
    """S1: npm is "latest version deprecated OR repo archived"; PyPI is "repo archived"."""
    if ecosystem == "npm":
        return _agreed([f[0] or f[1] for f in _fillings([latest_deprecated, archived])])
    return _agreed([f[0] for f in _fillings([archived])])


def s1b_oracle(ecosystem: str, resolved: bool | None, latest: bool | None) -> bool | None:
    """S1b: npm is "resolved deprecated AND latest not deprecated"; PyPI has no such signal."""
    if ecosystem != "npm":
        return None
    return _agreed([f[0] and not f[1] for f in _fillings([resolved, latest])])
