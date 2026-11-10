"""Fixed versions of an OSV advisory for one package (SRC-OSV-4, design §6.1).

``fixed_versions(vuln, ecosystem, name)`` walks ``vuln["affected"]`` and returns the sorted,
unique ``fixed`` event versions of the entries that describe the queried package:

* ``package.ecosystem`` equals ``ecosystem`` exactly;
* ``package.name`` equals ``name`` after PEP 503 normalisation (applied to both
  ecosystems, as the prototype does);
* ranges of type ``GIT`` are skipped (their ``fixed`` values are commit hashes);
* a ``fixed`` value counts only if it is a ``str`` that passes ``is_valid_version``
  (SRC-SEC-4). Anything else is ignored.

``has_fix`` is ``bool(fixed_versions(...))``.

The advisory is untrusted (SRC-SEC-4). Every level is read through the typed accessors, so
a value of the wrong type is skipped and nothing here raises. The argument is not mutated.

Ported from the prototype's ``osv_fixed_versions`` (``scripts/capture_anchors.py``) with
explicit type checks.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from core.purl import normalise_pypi_name
from core.sources.accessors import as_list, as_mapping, as_str
from core.sources.facts import is_valid_version


def fixed_versions(vuln: object, ecosystem: str, name: str) -> tuple[str, ...]:
    """Sorted, unique, valid ``fixed`` versions of ``vuln`` for ``ecosystem``/``name``."""
    doc = as_mapping(vuln)
    if doc is None:
        return ()
    affected = as_list(doc.get("affected"))
    if affected is None:
        return ()
    wanted = normalise_pypi_name(name)
    found: set[str] = set()
    for entry in affected:
        aff = as_mapping(entry)
        if aff is None:
            continue
        pkg = as_mapping(aff.get("package"))
        if pkg is None:
            continue
        pkg_name = as_str(pkg.get("name"))
        if pkg.get("ecosystem") != ecosystem or pkg_name is None:
            continue
        if normalise_pypi_name(pkg_name) != wanted:
            continue
        found.update(_range_fixes(aff.get("ranges")))
    return tuple(sorted(found))


def has_fix(vuln: object, ecosystem: str, name: str) -> bool:
    """True iff ``fixed_versions`` finds at least one valid fixed version."""
    return bool(fixed_versions(vuln, ecosystem, name))


def _range_fixes(ranges: object) -> set[str]:
    """Valid ``fixed`` strings in the non-``GIT`` ranges of one ``affected`` entry."""
    out: set[str] = set()
    range_list = as_list(ranges)
    if range_list is None:
        return out
    for item in range_list:
        rng = as_mapping(item)
        if rng is None or rng.get("type") == "GIT":
            continue
        events = as_list(rng.get("events"))
        if events is None:
            continue
        for raw_event in events:
            event = as_mapping(raw_event)
            if event is None:
                continue
            fixed = as_str(event.get("fixed"))
            if fixed is not None and is_valid_version(fixed):
                out.add(fixed)
    return out
