"""Independent oracles for the ``core.sources`` property tests.

``has_fix_oracle`` (SRC-TEST-3, design §6.1) answers the same question as
``core.sources.osv_fix.has_fix`` by a different method. Instead of looking keys up level
by level, it flattens the whole document into ``(path, value)`` pairs and then asks
"does a path of this shape exist?". A guard that one implementation forgets, such as a
missing ``type`` or a wrongly typed ``package``, then shows up as a counterexample.

This module must stay independent of the code it checks. It imports only the standard
library, repeats the version pattern (SRC-SEC-4) and the PEP 503 normaliser instead of
importing them, and ``test_oracles_independence.py`` enforces that with ``ast``.
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


def _is_fixed_path(path: Path) -> bool:
    """True for ``("affected", i, "ranges", j, "events", k, "fixed")`` with int i, j, k."""
    return (
        len(path) == 7
        and path[0] == "affected"
        and isinstance(path[1], int)
        and path[2] == "ranges"
        and isinstance(path[3], int)
        and path[4] == "events"
        and isinstance(path[5], int)
        and path[6] == "fixed"
    )


def has_fix_oracle(doc: object, ecosystem: str, name: str) -> bool:
    """True iff ``doc`` has a valid ``fixed`` event for the package outside ``GIT`` ranges.

    The ``fixed`` event must sit at ``affected[i].ranges[j].events[k].fixed`` where
    ``affected[i].package.ecosystem`` equals ``ecosystem``, ``affected[i].package.name`` is
    a ``str`` equal to ``name`` after PEP 503 normalisation, ``affected[i].ranges[j].type``
    is not ``"GIT"`` (an absent or odd type counts as not ``GIT``), and the value is a
    ``str`` that matches the version pattern in full.
    """
    flat = dict(flatten_pairs(doc))
    wanted = _normalise(name)
    for path, value in flat.items():
        if not _is_fixed_path(path):
            continue
        if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
            continue
        affected_index, range_index = path[1], path[3]
        package = ("affected", affected_index, "package")
        if flat.get((*package, "ecosystem")) != ecosystem:
            continue
        package_name = flat.get((*package, "name"))
        if not isinstance(package_name, str) or _normalise(package_name) != wanted:
            continue
        if flat.get(("affected", affected_index, "ranges", range_index, "type")) == "GIT":
            continue
        return True
    return False
