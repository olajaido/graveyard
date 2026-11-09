"""Example tests on the recorded Syft fixtures (T7.4; DG-EX-1, 2, 3, 23).

Every pinned figure is recomputed in the same test from the BOM with code that
does not use ``core.purl`` or ``core.graph``, so a swapped fixture fails loudly.
"""

from __future__ import annotations

import copy
import json
import random
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from core.graph.build import build_graph
from core.graph.model import DependencyGraph, ServiceInput
from core.graph.scopes_npm import parse_package_lock
from core.graph.scopes_uv import parse_uv_lock
from core.scoring.types import PathInfo

FIXTURES = Path(__file__).parent / "fixtures"

RT_D = PathInfo(runtime=True, direct=True)
RT_T = PathInfo(runtime=True, direct=False)

PY_KEYS = (
    "pypi/certifi@2026.10.23",
    "pypi/charset-normalizer@3.5.2",
    "pypi/idna@3.20",
    "pypi/nose@1.3.7",
    "pypi/requests@2.34.2",
    "pypi/six@1.17.0",
    "pypi/urllib3@2.8.0",
)
PY_DIRECT = ("pypi/nose@1.3.7", "pypi/requests@2.34.2", "pypi/six@1.17.0")

# Pinned figures for syft_npm.cdx.json (see test_fixtures.py).
NPM_NODES = 115
NPM_DIRECT = 4
NPM_EDGES = 197  # 193 between packages + 4 from the root
NPM_DIRECT_KEYS = ("npm/express@", "npm/jsonstream@", "npm/moment@", "npm/request@")


def _load_bom(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _key(purl: str) -> str:
    """Independent package key for npm/pypi purls: lower-cased, unquoted, no qualifiers."""
    body = unquote(purl.removeprefix("pkg:").split("?")[0].split("#")[0])
    return body.lower()


def _facts(bom: dict[str, Any]) -> tuple[dict[str, set[str]], set[str], str]:
    """Return ``(adjacency by key, direct keys, root bom-ref)`` computed from raw JSON."""
    by_ref = {c["bom-ref"]: c for c in bom["components"]}
    entries = {d["ref"]: d.get("dependsOn", []) for d in bom["dependencies"]}
    referenced = {t for ts in entries.values() for t in ts}
    (root,) = set(entries) - referenced
    adjacency: dict[str, set[str]] = {}
    for ref, targets in entries.items():
        if ref != root:
            adjacency[_key(by_ref[ref]["purl"])] = {_key(by_ref[t]["purl"]) for t in targets}
    directs = {_key(by_ref[t]["purl"]) for t in entries[root]}
    return adjacency, directs, root


def _library_keys(bom: dict[str, Any], root: str) -> set[str]:
    return {
        _key(c["purl"])
        for c in bom["components"]
        if c["type"] == "library" and c["bom-ref"] != root
    }


def _reachable(adjacency: dict[str, set[str]], directs: set[str]) -> set[str]:
    seen = set(directs)
    queue = deque(directs)
    while queue:
        for nxt in adjacency.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _codes(g: DependencyGraph) -> list[str]:
    return [w.code for w in g.warnings]


def _scramble(bom: dict[str, Any], mode: str, rng: random.Random) -> dict[str, Any]:
    out = copy.deepcopy(bom)
    lists = [out["components"], out["dependencies"]]
    lists += [d["dependsOn"] for d in out["dependencies"] if "dependsOn" in d]
    for items in lists:
        if mode == "reverse":
            items.reverse()
        else:
            rng.shuffle(items)
    return out


# --- DG-EX-1 -------------------------------------------------------------------


def test_dg_ex_1_syft_py_fixture() -> None:
    """DG-EX-1: nodes, path_infos, services_affected and SCOPE_ASSUMED for the py BOM."""
    bom = _load_bom("syft_py.cdx.json")
    adjacency, directs, root = _facts(bom)
    # Independent recomputation: the root and the file component are not nodes.
    assert _library_keys(bom, root) == set(PY_KEYS)
    assert directs == set(PY_DIRECT)
    assert _reachable(adjacency, directs) == set(PY_KEYS)
    assert [c["type"] for c in bom["components"]].count("file") == 1

    g = build_graph([ServiceInput("py", bom)])
    assert tuple(n.key for n in g.nodes) == PY_KEYS
    assert len(g.nodes) == 7
    for node in g.nodes:
        expected = (RT_D,) if node.key in PY_DIRECT else (RT_T,)
        assert node.path_infos == expected, node.key
        assert node.services_affected == 1
        assert node.manifests == ("py",)
    assert _codes(g) == ["SCOPE_ASSUMED"]
    assert g.warnings[0].subjects == PY_DIRECT
    assert g.warnings[0].service == "py"
    assert "ROOT_NOT_FOUND" not in _codes(g)
    # T8: urllib3.example_paths == (ExamplePath("py", ("pypi/requests@2.34.2",
    # T8: "pypi/urllib3@2.8.0")),) and its (runtime, transitive) witness is the same path.


# --- DG-EX-2 -------------------------------------------------------------------


def test_dg_ex_2_syft_npm_fixture() -> None:
    """DG-EX-2: pinned node/direct/edge counts, recomputed; all reachable; no ROOT_NOT_FOUND."""
    bom = _load_bom("syft_npm.cdx.json")
    adjacency, directs, root = _facts(bom)
    edges = sum(len(ts) for ts in adjacency.values()) + len(directs)
    keys = _library_keys(bom, root)
    assert (len(keys), len(directs), edges) == (NPM_NODES, NPM_DIRECT, NPM_EDGES)
    assert _reachable(adjacency, directs) == keys

    g = build_graph([ServiceInput("npm", bom)])
    assert {n.key for n in g.nodes} == keys
    assert len(g.nodes) == NPM_NODES
    assert all(n.path_infos and n.services_affected == 1 for n in g.nodes)
    direct_nodes = {n.key for n in g.nodes if n.direct}
    assert direct_nodes == directs
    assert len(direct_nodes) == NPM_DIRECT
    assert {k.split("@")[0] + "@" for k in direct_nodes} == set(NPM_DIRECT_KEYS)
    assert "ROOT_NOT_FOUND" not in _codes(g)
    assert "MULTIPLE_ROOTS" not in _codes(g)
    assert _codes(g) == ["SCOPE_ASSUMED"]
    assert g.warnings[0].subjects == tuple(sorted(directs))


def test_dg_ex_2_metadata_component_is_irrelevant() -> None:
    """DG-EX-2 (DG-ROOT-2): removing or nulling metadata.component changes nothing."""
    bom = _load_bom("syft_npm.cdx.json")
    expected = build_graph([ServiceInput("npm", bom)])
    removed = copy.deepcopy(bom)
    del removed["metadata"]["component"]
    nulled = copy.deepcopy(bom)
    nulled["metadata"]["component"] = None
    assert build_graph([ServiceInput("npm", removed)]) == expected
    assert build_graph([ServiceInput("npm", nulled)]) == expected


# --- DG-EX-3 -------------------------------------------------------------------


def test_dg_ex_3_order_independence_on_real_data() -> None:
    """DG-EX-3: reversing and shuffling lists in both fixtures gives an equal graph."""
    for name in ("syft_py.cdx.json", "syft_npm.cdx.json"):
        bom = _load_bom(name)
        expected = build_graph([ServiceInput("svc", bom)])
        assert len(expected.nodes) in (7, NPM_NODES)
        reversed_bom = _scramble(bom, "reverse", random.Random(0))
        assert build_graph([ServiceInput("svc", reversed_bom)]) == expected, name
        for seed in (1, 2, 3):
            shuffled = _scramble(bom, "shuffle", random.Random(seed))
            assert build_graph([ServiceInput("svc", shuffled)]) == expected, (name, seed)


# --- DG-EX-23 ------------------------------------------------------------------


def test_dg_ex_23_uv_lock_gives_same_paths_and_no_scope_assumed() -> None:
    """DG-EX-23: parse_uv_lock + the py BOM: no SCOPE_ASSUMED; path_infos as DG-EX-1."""
    bom = _load_bom("syft_py.cdx.json")
    scopes = parse_uv_lock((FIXTURES / "lock_uv.toml").read_text(encoding="utf-8"))
    g = build_graph([ServiceInput("py", bom, scopes)])
    plain = build_graph([ServiceInput("py", bom)])
    assert "SCOPE_ASSUMED" not in _codes(g)
    assert len(g.nodes) == 7
    assert [(n.key, n.path_infos) for n in g.nodes] == [(n.key, n.path_infos) for n in plain.nodes]
    for node in g.nodes:
        assert node.path_infos == ((RT_D,) if node.key in PY_DIRECT else (RT_T,))


def test_dg_ex_23_package_lock_gives_no_scope_assumed() -> None:
    """DG-EX-23: parse_package_lock + the npm BOM: no SCOPE_ASSUMED, all runtime."""
    bom = _load_bom("syft_npm.cdx.json")
    _, directs, _ = _facts(bom)
    scopes = parse_package_lock((FIXTURES / "lock_npm.json").read_text(encoding="utf-8"))
    g = build_graph([ServiceInput("npm", bom, scopes)])
    assert "SCOPE_ASSUMED" not in _codes(g)
    assert len(g.nodes) == NPM_NODES
    assert all(p.runtime for n in g.nodes for p in n.path_infos)
    assert {n.key for n in g.nodes if n.direct} == directs
