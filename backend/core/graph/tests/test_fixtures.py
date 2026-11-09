"""Fixture integrity for core/graph (DG-NFR-3, DG-NFR-6, DG-ROOT-2; SPIKES Q5, Q6).

Pinned counts are re-computed here from the BOM itself, so a swapped or
re-recorded fixture fails loudly instead of passing on stale constants.
"""

import json
import re
import tomllib
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from core.purl import package_key, parse_purl

FIXTURES = Path(__file__).parent / "fixtures"
BOM_NAMES = ("syft_npm.cdx.json", "syft_py.cdx.json")
TEXT_NAMES = (*BOM_NAMES, "lock_npm.json", "lock_uv.toml", "README.md")
NPM_ROOT_CHILDREN = ["JSONStream", "express", "moment", "request"]

# Pinned figures for syft_npm.cdx.json (docs/SPIKES.md, Q5 addendum).
NPM_LIBRARY_COMPONENTS = 116
NPM_FILE_COMPONENTS = 1
NPM_DEPENDENCY_ENTRIES = 47
NPM_NON_ROOT_EDGES = 193
NPM_ROOT_EDGES = 4
NPM_REACHABLE_FROM_ROOT = 115

_DRIVE_LETTER = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")


def _load(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _component_refs(bom: dict[str, Any]) -> set[str]:
    return {c["bom-ref"] for c in bom["components"]}


def _unreferenced_dependency_refs(bom: dict[str, Any]) -> set[str]:
    referenced = {r for d in bom["dependencies"] for r in d.get("dependsOn", [])}
    return {d["ref"] for d in bom["dependencies"]} - referenced


def _root_ref(bom: dict[str, Any]) -> str:
    (root,) = _unreferenced_dependency_refs(bom)
    return root


@pytest.mark.parametrize("name", TEXT_NAMES)
def test_no_local_paths(name: str) -> None:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    assert "/Users/" not in text
    assert "/home/" not in text
    assert _DRIVE_LETTER.search(text) is None


def test_metadata_component_names_are_neutral() -> None:
    assert _load("syft_npm.cdx.json")["metadata"]["component"]["name"] == "fixtures/npm"
    assert _load("syft_py.cdx.json")["metadata"]["component"]["name"] == "fixtures/py"


@pytest.mark.parametrize("name", BOM_NAMES)
def test_spec_version(name: str) -> None:
    assert _load(name)["specVersion"] == "1.7"


@pytest.mark.parametrize("name", BOM_NAMES)
def test_every_dependency_ref_is_a_component(name: str) -> None:
    bom = _load(name)
    refs = _component_refs(bom)
    for entry in bom["dependencies"]:
        assert entry["ref"] in refs
        for target in entry.get("dependsOn", []):
            assert target in refs


@pytest.mark.parametrize("name", BOM_NAMES)
def test_exactly_one_unreferenced_ref_and_it_is_a_component(name: str) -> None:
    bom = _load(name)
    unreferenced = _unreferenced_dependency_refs(bom)
    assert len(unreferenced) == 1
    assert unreferenced <= _component_refs(bom)


@pytest.mark.parametrize("name", BOM_NAMES)
def test_metadata_root_ref_is_in_neither_components_nor_dependencies(name: str) -> None:
    bom = _load(name)
    meta_ref = bom["metadata"]["component"]["bom-ref"]
    assert meta_ref not in _component_refs(bom)
    assert meta_ref not in {d["ref"] for d in bom["dependencies"]}
    assert meta_ref not in {r for d in bom["dependencies"] for r in d.get("dependsOn", [])}


def test_jsonstream_purl_and_bom_ref_case() -> None:
    bom = _load("syft_npm.cdx.json")
    (component,) = [c for c in bom["components"] if c.get("name") == "JSONStream"]
    assert component["purl"] == "pkg:npm/JSONStream@1.3.5"
    assert component["bom-ref"].startswith("pkg:npm/jsonstream@1.3.5?package-id=")


def test_npm_root_children() -> None:
    bom = _load("syft_npm.cdx.json")
    by_ref = {c["bom-ref"]: c for c in bom["components"]}
    root = _root_ref(bom)
    (entry,) = [d for d in bom["dependencies"] if d["ref"] == root]
    assert sorted(by_ref[r]["name"] for r in entry["dependsOn"]) == NPM_ROOT_CHILDREN


def test_npm_pinned_counts_match_recomputed_values() -> None:
    bom = _load("syft_npm.cdx.json")
    components = bom["components"]
    by_ref = {c["bom-ref"]: c for c in components}
    root = _root_ref(bom)

    def key(ref: str) -> str:
        return package_key(parse_purl(by_ref[ref]["purl"]))

    library = [c for c in components if c["type"] == "library"]
    files = [c for c in components if c["type"] == "file"]
    assert len(library) == NPM_LIBRARY_COMPONENTS
    assert len(files) == NPM_FILE_COMPONENTS
    assert len(library) + len(files) == len(components)
    assert len(bom["dependencies"]) == NPM_DEPENDENCY_ENTRIES

    non_root_edges: set[tuple[str, str]] = set()
    root_children: set[str] = set()
    for entry in bom["dependencies"]:
        targets = [key(t) for t in entry.get("dependsOn", [])]
        if entry["ref"] == root:
            root_children.update(targets)
        else:
            non_root_edges.update((key(entry["ref"]), t) for t in targets)
    assert len(non_root_edges) == NPM_NON_ROOT_EDGES
    assert len(root_children) == NPM_ROOT_EDGES

    adjacency: dict[str, set[str]] = {}
    for source, target in non_root_edges:
        adjacency.setdefault(source, set()).add(target)
    seen = set(root_children)
    queue = deque(root_children)
    while queue:
        node = queue.popleft()
        for nxt in adjacency.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    assert len(seen) == NPM_REACHABLE_FROM_ROOT
    # Every package other than the project itself is reachable from the root.
    package_keys = {key(c["bom-ref"]) for c in library if c["bom-ref"] != root}
    assert seen == package_keys


def test_py_fixture_shape() -> None:
    bom = _load("syft_py.cdx.json")
    by_ref = {c["bom-ref"]: c for c in bom["components"]}
    assert len(bom["components"]) == 9
    assert sum(c["type"] == "file" for c in bom["components"]) == 1
    assert len(bom["dependencies"]) == 2
    (entry,) = [d for d in bom["dependencies"] if d["ref"] == _root_ref(bom)]
    assert sorted(by_ref[r]["name"] for r in entry["dependsOn"]) == ["nose", "requests", "six"]


def test_lock_npm_root_dependencies_match_sbom_root_children() -> None:
    lock = _load("lock_npm.json")
    declared = lock["packages"][""]["dependencies"]
    assert sorted(declared) == NPM_ROOT_CHILDREN
    assert len(lock["packages"]) == 116


def test_lock_uv_has_one_virtual_project_package() -> None:
    lock = tomllib.loads((FIXTURES / "lock_uv.toml").read_text(encoding="utf-8"))
    projects = [p for p in lock["package"] if "virtual" in p.get("source", {})]
    assert len(projects) == 1
    assert sorted(d["name"] for d in projects[0]["dependencies"]) == ["nose", "requests", "six"]
