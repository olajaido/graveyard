"""Unit tests for ``cli.augment`` (T12.5; CLI-AUG-1…4, CLI-AUG-8).

The documents are built by hand in the shape the real Syft 1.56.0 writes (the real fixtures
are tested in ``test_augment_fixtures.py``). ``core.graph`` is used as the judge: the point of
the module is that the graph it produces is the right one.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from cli.augment import AugmentResult, add_direct_edges
from core.graph import ScopeResult, ServiceInput, build_graph
from core.graph.model import Scope, scope_map

META = "7dc828292c81995f"  # Syft's metadata.component bom-ref: a directory hash, not a component


def ref_of(name: str, eco: str = "npm") -> str:
    return f"pkg:{eco}/{name}@1.0.0?package-id=h{name}"


def key_of(name: str, eco: str = "npm") -> str:
    return f"{eco}/{name}@1.0.0"


def comp(
    name: str, eco: str = "npm", *, ref: str | None = None, nested: Any = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "bom-ref": ref or ref_of(name, eco),
        "type": "library",
        "name": name,
        "version": "1.0.0",
        "purl": f"pkg:{eco}/{name}@1.0.0",
    }
    if nested is not None:
        out["components"] = nested
    return out


def bom(
    names: list[str],
    edges: Mapping[str, list[str]],
    *,
    meta: str | None = META,
    eco: str = "npm",
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "components": [comp(n, eco) for n in names],
        "dependencies": [
            {"ref": ref_of(source, eco), "dependsOn": [ref_of(t, eco) for t in targets]}
            for source, targets in edges.items()
        ],
    }
    if meta is not None:
        document["metadata"] = {"component": {"bom-ref": meta, "type": "file", "name": "x"}}
    return document


def scopes(**declared: Scope) -> dict[str, Scope]:
    return {key_of(name): scope for name, scope in declared.items()}


def root_children(document: Mapping[str, Any], root: str) -> list[str]:
    for entry in document["dependencies"]:
        if entry["ref"] == root:
            return list(entry["dependsOn"])
    return []


def graph_of(document: Mapping[str, Any], direct: Mapping[str, Scope]) -> Any:
    result = ScopeResult(
        package_scopes=scope_map(dict(direct)), direct_scopes=scope_map(dict(direct)), warnings=()
    )
    return build_graph([ServiceInput(path="web", bom=document, scopes=result)])


# --------------------------------------------------------------- the real-shaped web service


def web_bom() -> dict[str, Any]:
    return bom(
        ["web", "express", "left-pad", "moment", "node-uuid", "request", "uuid"],
        {
            "web": ["express", "left-pad", "moment"],
            "express": ["node-uuid"],
            "request": ["uuid"],
        },
    )


WEB_DIRECT: dict[str, Scope] = {
    key_of("express"): "runtime",
    key_of("left-pad"): "runtime",
    key_of("moment"): "runtime",
    key_of("request"): "dev",
}


def test_web_the_orphan_dev_direct_gets_a_root_edge() -> None:
    result = add_direct_edges(web_bom(), WEB_DIRECT)
    assert isinstance(result, AugmentResult)
    assert result.added_keys == (key_of("request"),)
    assert result.missing_keys == ()
    assert root_children(result.bom, ref_of("web")) == [
        ref_of("express"),
        ref_of("left-pad"),
        ref_of("moment"),
        ref_of("request"),
    ]


def test_web_without_augmentation_the_graph_loses_request_and_finds_two_roots() -> None:
    """The hazard behind D21: this is what the unaugmented real Syft output does."""
    graph = graph_of(web_bom(), WEB_DIRECT)
    assert "MULTIPLE_ROOTS" in {w.code for w in graph.warnings}
    assert graph.node(key_of("request")) is None  # dropped as a root component


def test_web_with_augmentation_the_graph_is_right() -> None:
    result = add_direct_edges(web_bom(), WEB_DIRECT)
    graph = graph_of(result.bom, WEB_DIRECT)
    assert graph.warnings == ()
    request, uuid = graph.node(key_of("request")), graph.node(key_of("uuid"))
    assert request is not None and uuid is not None
    assert [(p.runtime, p.direct) for p in request.path_infos] == [(False, True)]
    assert [(p.runtime, p.direct) for p in uuid.path_infos] == [(False, False)]
    node_uuid = graph.node(key_of("node-uuid"))
    assert node_uuid is not None
    assert [(p.runtime, p.direct) for p in node_uuid.path_infos] == [(True, False)]


def test_api_a_leaf_dev_direct_with_no_entry_of_its_own_is_added() -> None:
    document = bom(["api", "nose", "pycrypto", "six"], {"api": ["pycrypto", "six"]}, eco="pypi")
    direct = {
        key_of("pycrypto", "pypi"): "runtime",
        key_of("six", "pypi"): "runtime",
        key_of("nose", "pypi"): "dev",
    }
    result = add_direct_edges(document, direct)
    assert result.added_keys == (key_of("nose", "pypi"),)
    assert ref_of("nose", "pypi") in root_children(result.bom, ref_of("api", "pypi"))


# ---------------------------------------------------------------------------- other shapes


def test_a_declared_key_with_no_component_is_missing_not_an_error() -> None:
    direct = {**WEB_DIRECT, key_of("ghost"): "dev", key_of("alpha"): "runtime"}
    result = add_direct_edges(web_bom(), direct)
    assert result.missing_keys == (key_of("alpha"), key_of("ghost"))
    assert result.added_keys == (key_of("request"),)


def test_a_dev_only_project_uses_the_metadata_component_as_the_root() -> None:
    """No `dependencies` entry for the project: only `request -> uuid` exists."""
    document = bom(["request", "uuid"], {"request": ["uuid"]})
    direct = scopes(request="dev")
    result = add_direct_edges(document, direct)
    assert result.added_keys == (key_of("request"),)
    assert root_children(result.bom, META) == [ref_of("request")]
    graph = graph_of(result.bom, direct)
    assert graph.warnings == ()
    request = graph.node(key_of("request"))
    assert request is not None
    assert [(p.runtime, p.direct) for p in request.path_infos] == [(False, True)]
    assert graph.node(key_of("uuid")) is not None


def test_no_root_at_all_leaves_the_document_alone() -> None:
    document = bom(["a", "b"], {}, meta=None)
    result = add_direct_edges(document, scopes(a="runtime", b="runtime", zz="dev"))
    assert result.bom is document
    assert result.added_keys == ()
    assert result.missing_keys == (key_of("zz"),)


def test_two_undeclared_orphan_roots_are_ambiguous_and_nothing_is_added() -> None:
    document = bom(["a", "b", "x", "y", "d"], {"a": ["x"], "b": ["y"]}, meta=None)
    result = add_direct_edges(document, scopes(d="dev"))
    assert result.bom is document
    assert result.added_keys == ()


def test_a_package_present_twice_uses_the_smallest_ref() -> None:
    document = bom(["web", "express"], {"web": ["express"]})
    document["components"].append(comp("lib", ref="z-ref"))
    document["components"].append(comp("lib", ref="a-ref"))
    result = add_direct_edges(document, scopes(express="runtime", lib="dev"))
    assert result.added_keys == (key_of("lib"),)
    assert root_children(result.bom, ref_of("web"))[-1] == "a-ref"


def test_a_key_already_reached_through_another_ref_is_not_added_again() -> None:
    document = bom(["web"], {"web": []})
    document["components"].append(comp("lib", ref="r1"))
    document["components"].append(comp("lib", ref="r2"))
    document["dependencies"][0]["dependsOn"] = ["r2"]
    result = add_direct_edges(document, scopes(lib="runtime"))
    assert result.added_keys == ()
    assert result.bom is document


def test_the_root_itself_is_never_given_an_edge_to_itself() -> None:
    document = bom(["app", "dep"], {"app": ["dep"]}, meta=ref_of("app"))
    result = add_direct_edges(document, scopes(app="runtime", dep="runtime"))
    assert result.added_keys == ()


def test_a_component_without_a_bom_ref_cannot_be_a_target() -> None:
    document = bom(["web", "express"], {"web": ["express"]})
    orphan = comp("lib")
    del orphan["bom-ref"]
    document["components"].append(orphan)
    result = add_direct_edges(document, scopes(express="runtime", lib="dev"))
    assert result.missing_keys == (key_of("lib"),)
    assert result.added_keys == ()


def test_nested_components_are_found() -> None:
    document = bom(["web"], {"web": []})
    document["components"][0]["components"] = [comp("inner")]
    result = add_direct_edges(document, scopes(inner="dev"))
    assert result.added_keys == (key_of("inner"),)


def test_unsupported_purls_are_neither_targets_nor_errors() -> None:
    document = bom(["web", "express"], {"web": ["express"]})
    document["components"].append(
        {"bom-ref": "mvn", "type": "library", "name": "m", "purl": "pkg:maven/g/a@1"}
    )
    result = add_direct_edges(document, scopes(express="runtime"))
    assert result.added_keys == ()
    assert result.missing_keys == ()


# --------------------------------------------------------------------------------- safety


def test_the_input_is_never_mutated() -> None:
    document = web_bom()
    before = copy.deepcopy(document)
    result = add_direct_edges(document, WEB_DIRECT)
    assert document == before
    assert result.bom is not document
    assert root_children(document, ref_of("web")) == [
        ref_of("express"),
        ref_of("left-pad"),
        ref_of("moment"),
    ]


def test_components_and_original_edges_are_preserved() -> None:
    document = web_bom()
    result = add_direct_edges(document, WEB_DIRECT)
    assert result.bom["components"] == document["components"]
    assert result.bom["metadata"] == document["metadata"]
    originals = {e["ref"]: e["dependsOn"] for e in document["dependencies"]}
    for entry in result.bom["dependencies"]:
        old = originals[entry["ref"]]
        assert entry["dependsOn"][: len(old)] == old
    assert len(result.bom["dependencies"]) == len(document["dependencies"])


def test_idempotent() -> None:
    once = add_direct_edges(web_bom(), WEB_DIRECT)
    twice = add_direct_edges(once.bom, WEB_DIRECT)
    assert twice.bom == once.bom
    assert twice.added_keys == ()
    assert twice.missing_keys == once.missing_keys


def test_nothing_to_add_returns_the_same_object() -> None:
    document = web_bom()
    result = add_direct_edges(document, scopes(express="runtime", moment="runtime"))
    assert result.bom is document
    assert result == AugmentResult(document, (), ())


def test_empty_direct_scopes() -> None:
    document = web_bom()
    assert add_direct_edges(document, {}) == AugmentResult(document, (), ())


def test_added_refs_follow_sorted_key_order() -> None:
    # `web` has an empty entry, which is not a root by core.graph's rule, so the metadata
    # component is the root and receives the edges.
    document = bom(["web", "c", "a", "b"], {"web": []})
    result = add_direct_edges(document, scopes(c="dev", a="dev", b="dev"))
    assert result.added_keys == (key_of("a"), key_of("b"), key_of("c"))
    assert root_children(result.bom, META) == [ref_of("a"), ref_of("b"), ref_of("c")]


# ------------------------------------------------------------------------ unreadable input


def test_malformed_documents_are_returned_unchanged() -> None:
    cases: list[Any] = [
        "not a mapping",
        None,
        {"components": "nope"},
        {"components": [1]},
        {"components": [{"bom-ref": "a", "components": "x"}]},
        {"components": [], "dependencies": "nope"},
        {"components": [], "dependencies": [1]},
        {"components": [], "dependencies": [{"ref": ""}]},
        {"components": [], "dependencies": [{"ref": "a", "dependsOn": "b"}]},
        {"components": [], "dependencies": [{"ref": "a", "dependsOn": [1]}]},
        {"components": [], "metadata": "x"},
        {"components": [], "metadata": {"component": "x"}},
    ]
    for case in cases:
        result = add_direct_edges(case, scopes(x="dev"))
        assert result.bom is case
        assert (result.added_keys, result.missing_keys) == ((), ())
