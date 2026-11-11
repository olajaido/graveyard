"""Property tests for ``cli.augment`` (T12.6; CLI-AUG-4, CLI-AUG-8, CLI-TEST-6).

The documents are generated so that the root can be told: any package that is an orphan with
edges of its own is declared as a direct dependency (that is exactly the situation the real
Syft output creates). The root has a `dependencies` entry in some cases and only the
`metadata.component` ref in others. Some declared keys have no component at all.

**Validates: Requirements CLI-AUG-2, CLI-AUG-3, CLI-AUG-4, CLI-AUG-6**
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.augment import add_direct_edges

pytestmark = pytest.mark.property

ROOT_REF = "root-ref"


@dataclass(frozen=True)
class Case:
    bom: dict[str, Any]
    direct: dict[str, str]
    component_keys: frozenset[str]  # package keys that have a component with a bom-ref


def _ref(name: str) -> str:
    return f"ref-{name}"


def _key(name: str) -> str:
    return f"npm/{name}@1.0.0"


@st.composite
def cases(draw: st.DrawFn) -> Case:
    count = draw(st.integers(min_value=1, max_value=8))
    names = [f"p{i}" for i in range(count)]
    edges: dict[str, list[str]] = {}
    for source in names:
        targets = draw(st.lists(st.sampled_from(names), max_size=3, unique=True))
        targets = [t for t in targets if t != source]
        if targets:
            edges[source] = targets
    root_children = draw(st.lists(st.sampled_from(names), max_size=3, unique=True))
    declared = set(draw(st.lists(st.sampled_from(names), max_size=4, unique=True)))
    ghosts = draw(st.lists(st.sampled_from(["g0", "g1", "g2"]), max_size=2, unique=True))

    children = {t for ts in edges.values() for t in ts} | set(root_children)
    for name, targets in edges.items():  # an orphan with edges must be a declared direct
        if targets and name not in children:
            declared.add(name)

    root_has_entry = bool(root_children) and draw(st.booleans())
    entries = [{"ref": _ref(n), "dependsOn": [_ref(t) for t in ts]} for n, ts in edges.items()]
    if root_has_entry:
        entries.append({"ref": ROOT_REF, "dependsOn": [_ref(t) for t in root_children]})
    if not root_has_entry and root_children:
        # the root reaches them, but only through a `dependencies` entry
        entries.append({"ref": ROOT_REF, "dependsOn": [_ref(t) for t in root_children]})
        root_has_entry = True
    draw(st.randoms(use_true_random=False)).shuffle(entries)

    components = [
        {
            "bom-ref": _ref(n),
            "type": "library",
            "name": n,
            "version": "1.0.0",
            "purl": f"pkg:npm/{n}@1.0.0",
        }
        for n in names
    ]
    document: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "metadata": {"component": {"bom-ref": ROOT_REF, "type": "file", "name": "x"}},
        "components": components,
        "dependencies": entries,
    }
    direct = {_key(n): draw(st.sampled_from(["runtime", "dev"])) for n in sorted(declared)}
    direct.update({_key(g): "dev" for g in ghosts})
    return Case(document, direct, frozenset(_key(n) for n in names))


def _edges(document: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (entry["ref"], target)
        for entry in document["dependencies"]
        for target in entry.get("dependsOn", [])
    }


def _root_child_keys(document: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for source, target in _edges(document):
        if source == ROOT_REF and target.startswith("ref-"):
            out.add(_key(target.removeprefix("ref-")))
    return out


@given(cases())
def test_only_root_sourced_edges_are_added(case: Case) -> None:
    result = add_direct_edges(case.bom, case.direct)
    new_edges = _edges(dict(result.bom)) - _edges(case.bom)
    assert {source for source, _ in new_edges} <= {ROOT_REF}
    assert len(new_edges) == len(result.added_keys)


@given(cases())
def test_input_is_unchanged(case: Case) -> None:
    before = copy.deepcopy(case.bom)
    add_direct_edges(case.bom, case.direct)
    assert case.bom == before


@given(cases())
def test_idempotent(case: Case) -> None:
    once = add_direct_edges(case.bom, case.direct)
    twice = add_direct_edges(once.bom, case.direct)
    assert twice.bom == once.bom
    assert twice.added_keys == ()
    assert twice.missing_keys == once.missing_keys


@given(cases())
def test_original_edges_and_components_are_preserved(case: Case) -> None:
    result = add_direct_edges(case.bom, case.direct)
    assert _edges(case.bom) <= _edges(dict(result.bom))
    assert result.bom["components"] == case.bom["components"]
    assert result.bom["metadata"] == case.bom["metadata"]
    old = {e["ref"]: e.get("dependsOn", []) for e in case.bom["dependencies"]}
    for entry in result.bom["dependencies"]:
        if entry["ref"] in old:
            assert entry["dependsOn"][: len(old[entry["ref"]])] == old[entry["ref"]]


@given(cases())
def test_every_direct_key_with_a_component_ends_up_a_root_child(case: Case) -> None:
    result = add_direct_edges(case.bom, case.direct)
    wanted = {k for k in case.direct if k in case.component_keys}
    assert wanted <= _root_child_keys(dict(result.bom))


@given(cases())
def test_missing_keys_are_exactly_the_declared_keys_without_a_component(case: Case) -> None:
    result = add_direct_edges(case.bom, case.direct)
    assert result.missing_keys == tuple(
        sorted(k for k in case.direct if k not in case.component_keys)
    )
    assert set(result.added_keys) <= set(case.direct)
    assert result.added_keys == tuple(sorted(result.added_keys))


@given(cases(), st.randoms(use_true_random=False))
def test_independent_of_entry_order_and_of_direct_scopes_order(
    case: Case, rnd: random.Random
) -> None:
    shuffled = copy.deepcopy(case.bom)
    rnd.shuffle(shuffled["dependencies"])
    items = list(case.direct.items())
    rnd.shuffle(items)
    first = add_direct_edges(case.bom, case.direct)
    second = add_direct_edges(shuffled, dict(items))
    assert first.added_keys == second.added_keys
    assert first.missing_keys == second.missing_keys
    assert _edges(dict(first.bom)) == _edges(dict(second.bom))
