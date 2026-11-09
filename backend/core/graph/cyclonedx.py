"""CycloneDX 1.5–1.7 ingest for one service (design §5.1, DG-ING-*, DG-ROOT-*, DG-DUP-*).

``parse_service`` validates the envelope of an already-parsed BOM, flattens
nested components with an explicit stack, maps every component to a
``package_key`` through ``core.purl`` and finds the service root(s). It returns
the packages, the direct dependencies of the root(s) and the per-service
adjacency, plus warnings for everything recoverable.

Identity is ``package_key`` (D1). A ``bom-ref`` is an opaque string used only
for exact-match resolution of ``dependencies``; the ``?package-id=`` suffix is
never parsed, stripped or compared. Every result is a function of the multiset
of components and entries, never of their order (DG-ROOT-5, DG-OUT-1): all
order-sensitive steps go through sets or ``min`` and are sorted afterwards.

Structural errors raise ``ValueError("<service>: <field>: <rule>")``. The
message never repeats input values, so it cannot carry attacker-controlled
text. This module does no I/O and emits no diagnostics beyond the returned
``GraphWarning`` values (D14).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NamedTuple

from core.graph.diagnostics import finalise_warnings, make_warning
from core.graph.model import (
    DEFAULT_MAX_COMPONENTS,
    DEFAULT_MAX_EDGES,
    SUPPORTED_SPEC_VERSIONS,
    GraphWarning,
)
from core.purl import format_purl, package_key, parse_purl

_LIBRARY_TYPES = frozenset({"library", "application"})


@dataclass(frozen=True)
class IngestLimits:
    """Size limits for one BOM (DG-ING-8). ``build_graph`` passes its keyword arguments."""

    max_components: int = DEFAULT_MAX_COMPONENTS
    max_edges: int = DEFAULT_MAX_EDGES


@dataclass(frozen=True)
class ParsedService:
    path: str
    packages: Mapping[str, str]  # package_key -> smallest canonical purl (DG-DUP-3)
    directs: tuple[str, ...]  # sorted package_keys that a root depends on
    adj: Mapping[str, tuple[str, ...]]  # package_key -> sorted successors; leaves are absent
    warnings: tuple[GraphWarning, ...]  # service stamped; finalised


class _Component(NamedTuple):
    label: str  # field path used in error messages, e.g. "components[3].components[0]"
    ref: str | None  # bom-ref
    purl: str | None
    kind: str | None  # CycloneDX "type"
    name: str | None


def _err(path: str, field: str, rule: str) -> ValueError:
    return ValueError(f"{path}: {field}: {rule}")


def _optional_mapping(path: str, container: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    """Return ``container[field]`` as a mapping; absent or null gives an empty mapping."""
    value = container.get(field)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _err(path, field, "must be a mapping")
    return value


def _check_envelope(path: str, bom: object) -> Mapping[str, Any]:
    if not isinstance(bom, Mapping):
        raise _err(path, "bom", "must be a mapping")
    if "bomFormat" in bom and bom["bomFormat"] != "CycloneDX":
        raise _err(path, "bomFormat", 'must be "CycloneDX" when present')
    spec = bom.get("specVersion")
    if not isinstance(spec, str):
        raise _err(path, "specVersion", "must be a string")
    if spec not in SUPPORTED_SPEC_VERSIONS:
        raise _err(path, "specVersion", "must be one of " + ", ".join(SUPPORTED_SPEC_VERSIONS))
    return bom


def _metadata_root_ref(path: str, bom: Mapping[str, Any]) -> str | None:
    """Return ``metadata.component.bom-ref``, or ``None`` when absent or null."""
    metadata = _optional_mapping(path, bom, "metadata")
    component = _optional_mapping(path, metadata, "component")
    if "bom-ref" not in component:
        return None
    ref = component["bom-ref"]
    if not isinstance(ref, str) or not ref:
        raise _err(path, "metadata.component.bom-ref", "must be a non-empty string")
    return ref


def _flatten(path: str, bom: Mapping[str, Any], max_components: int) -> list[_Component]:
    """Return every component at any depth, validating types (DG-ING-3, DG-ING-4)."""
    raw = bom.get("components", [])
    if not isinstance(raw, list):
        raise _err(path, "components", "must be a list")
    stack: list[tuple[str, Any]] = [(f"components[{i}]", c) for i, c in enumerate(raw)]
    out: list[_Component] = []
    while stack:
        label, comp = stack.pop()
        if not isinstance(comp, Mapping):
            raise _err(path, label, "must be a mapping")
        if len(out) >= max_components:
            raise _err(path, "components", f"more than {max_components} components (DG-ING-8)")
        ref = _string_field(path, label, comp, "bom-ref", non_empty=True)
        purl = _string_field(path, label, comp, "purl")
        kind = _string_field(path, label, comp, "type")
        name = comp.get("name")
        out.append(_Component(label, ref, purl, kind, name if isinstance(name, str) else None))
        if "components" in comp:
            nested = comp["components"]
            if not isinstance(nested, list):
                raise _err(path, f"{label}.components", "must be a list")
            stack.extend((f"{label}.components[{j}]", c) for j, c in enumerate(nested))
    return out


def _string_field(
    path: str, label: str, comp: Mapping[str, Any], field: str, *, non_empty: bool = False
) -> str | None:
    if field not in comp:
        return None
    value = comp[field]
    if not isinstance(value, str) or (non_empty and not value):
        rule = "must be a non-empty string" if non_empty else "must be a string"
        raise _err(path, f"{label}.{field}", rule)
    return value


def _dependency_entries(path: str, bom: Mapping[str, Any]) -> dict[str, set[str]]:
    """Return ``ref -> union of dependsOn`` over all ``dependencies`` entries (DG-DUP-2)."""
    raw = bom.get("dependencies", [])
    if not isinstance(raw, list):
        raise _err(path, "dependencies", "must be a list")
    deps: dict[str, set[str]] = {}
    for i, entry in enumerate(raw):
        label = f"dependencies[{i}]"
        if not isinstance(entry, Mapping):
            raise _err(path, label, "must be a mapping")
        ref = entry.get("ref")
        if not isinstance(ref, str) or not ref:
            raise _err(path, f"{label}.ref", "must be a non-empty string")
        targets: set[str] = deps.setdefault(ref, set())
        if "dependsOn" in entry:
            depends_on = entry["dependsOn"]
            if not isinstance(depends_on, list) or not all(isinstance(t, str) for t in depends_on):
                raise _err(path, f"{label}.dependsOn", "must be a list of strings")
            targets.update(depends_on)
    return deps


def parse_service(path: str, bom: Mapping[str, Any], limits: IngestLimits) -> ParsedService:
    """Parse one CycloneDX BOM into packages, directs and adjacency.

    Raises ``ValueError("<path>: <field>: <rule>")`` for structural errors
    (DG-ING-2, 3, 7, 8). Everything else that can be skipped becomes a warning.
    """
    document = _check_envelope(path, bom)
    meta_ref = _metadata_root_ref(path, document)
    components = _flatten(path, document, limits.max_components)
    deps = _dependency_entries(path, document)

    warnings: list[GraphWarning] = []

    # Map components to package keys (DG-ING-5). ``ref_to_key`` holds ``None`` for
    # components that were skipped, so a ``dependsOn`` to them is dangling.
    ref_to_key: dict[str, str | None] = {}
    kept: list[tuple[str | None, str, str]] = []  # (bom-ref, key, display purl)
    for comp in components:
        key: str | None = None
        display = ""
        if comp.purl is None:
            if comp.kind in _LIBRARY_TYPES:
                warnings.append(
                    make_warning(
                        "MISSING_PURL",
                        f"{comp.kind} component has no purl",
                        path,
                        (comp.ref or comp.name or "(unnamed)",),
                    )
                )
        else:
            try:
                purl_obj = parse_purl(comp.purl)
                key = package_key(purl_obj)
                display = format_purl(dataclasses.replace(purl_obj, qualifiers=(), subpath=None))
            except ValueError as exc:
                key = None
                warnings.append(
                    make_warning(
                        "UNSUPPORTED_PURL",
                        f"purl rejected: {exc}",
                        path,
                        (comp.ref or comp.purl,),
                    )
                )
        if comp.ref is not None:
            if comp.ref in ref_to_key and ref_to_key[comp.ref] != key:
                raise _err(
                    path,
                    f"{comp.label}.bom-ref",
                    "shared by components that map to different packages (DG-ING-7)",
                )
            ref_to_key[comp.ref] = key
        if key is not None:
            kept.append((comp.ref, key, display))

    # Find the root entries (DG-ROOT-1…4). The decision uses the whole BOM and
    # sets only, so it does not depend on order (DG-ROOT-5).
    children: set[str] = set()
    for targets in deps.values():
        children |= targets
    roots = {
        ref
        for ref, targets in deps.items()
        if ref not in children and (ref == meta_ref or (ref in ref_to_key and targets))
    }

    # Packages: one per key, smallest display purl, root components dropped (DG-ROOT-3).
    chosen: dict[str, str] = {}
    for ref, key, display in kept:
        if ref is not None and ref in roots:
            continue
        if key not in chosen or display < chosen[key]:
            chosen[key] = display
    packages = {key: chosen[key] for key in sorted(chosen)}

    def usable(ref: str) -> str | None:
        """Return the package key a ref resolves to, or ``None`` if root, skipped or unknown."""
        return None if ref in roots else ref_to_key.get(ref)

    # Edges (DG-ING-6, DG-ING-10, DG-DUP-1).
    directs: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    dangling_targets: set[str] = set()
    dangling_sources: set[str] = set()
    for ref, targets in deps.items():
        if ref in roots:
            for target in targets:
                if target in roots:
                    continue
                resolved = usable(target)
                if resolved is None:
                    dangling_targets.add(target)
                else:
                    directs.add(resolved)
            continue
        if ref not in ref_to_key:
            if ref != meta_ref:
                dangling_sources.add(ref)
            continue
        source = usable(ref)
        if source is None:
            continue
        for target in targets:
            if target in roots:
                continue
            resolved = usable(target)
            if resolved is None:
                dangling_targets.add(target)
            elif resolved != source:
                pairs.add((source, resolved))
                if len(pairs) > limits.max_edges:
                    raise _err(
                        path, "dependencies", f"more than {limits.max_edges} edges (DG-ING-8)"
                    )

    for target in dangling_targets:
        warnings.append(
            make_warning(
                "DANGLING_REF", "dependsOn target matches no usable component", path, (target,)
            )
        )
    for source_ref in dangling_sources:
        warnings.append(
            make_warning(
                "DANGLING_REF", "dependencies ref matches no component", path, (source_ref,)
            )
        )

    if not roots:
        warnings.append(
            make_warning("ROOT_NOT_FOUND", "no dependencies entry is a service root", path)
        )
    elif len(roots) > 1:
        warnings.append(
            make_warning(
                "MULTIPLE_ROOTS",
                f"{len(roots)} root entries found; their children are unioned",
                path,
                roots,
            )
        )

    successors: dict[str, list[str]] = {}
    for source_key, target_key in pairs:
        successors.setdefault(source_key, []).append(target_key)
    adj = {k: tuple(sorted(successors[k])) for k in sorted(successors)}

    return ParsedService(
        path=path,
        packages=MappingProxyType(packages),
        directs=tuple(sorted(directs)),
        adj=MappingProxyType(adj),
        warnings=finalise_warnings(warnings),
    )
