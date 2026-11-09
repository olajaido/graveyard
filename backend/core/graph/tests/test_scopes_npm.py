"""Unit tests for ``parse_package_lock`` (DG-SCP-0…5, DG-WARN-1, DG-EX-18, DG-EX-19).

Expectations for the recorded and generated fixtures (``lock_npm.json``,
``lock_npm_dev.json``) are recomputed here from the file with plain ``json``
code; ``parse_package_lock`` is never used to compute an expectation. Expected
keys come from ``core.graph.keys.npm_key``. Fixtures resolve via
``Path(__file__).parent``.

``build_graph`` does not exist yet (T7). The one assertion that needs it
(DG-EX-19, silent devDependency) is skipped while ``core.graph.build`` is not
importable and must be activated and verified in T7.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from core.graph.keys import npm_key
from core.graph.model import MAX_LOCKFILE_CHARS, WARNING_CODES, Scope, ScopeResult
from core.graph.scopes_common import check_size, cross_check, load_json
from core.graph.scopes_npm import parse_package_lock
from core.purl import package_key, parse_purl
from core.scoring.types import PathInfo

FIXTURES = Path(__file__).parent / "fixtures"
NODE_MODULES = "node_modules/"


# --- helpers ---------------------------------------------------------------


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def lock_text(packages: dict[str, Any]) -> str:
    return json.dumps({"lockfileVersion": 3, "requires": True, "packages": packages})


def entry_key(path: str, entry: dict[str, Any]) -> str:
    """Key of an installed entry: its own ``name`` if any, else the last path segment."""
    name = entry.get("name") or path.rsplit(NODE_MODULES, 1)[1]
    return npm_key(name, entry["version"])


def installed(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Installed entries: has ``node_modules/`` in the path, is not the root, is not a link."""
    return {
        path: entry
        for path, entry in doc["packages"].items()
        if path != "" and NODE_MODULES in path and not entry.get("link")
    }


def expected_package_scopes(doc: dict[str, Any]) -> dict[str, str]:
    """Per-package scope from the ``dev`` flag alone; any runtime copy wins."""
    out: dict[str, str] = {}
    for path, entry in installed(doc).items():
        key = entry_key(path, entry)
        if entry.get("dev") is True:
            out.setdefault(key, "dev")
        else:
            out[key] = "runtime"
    return out


def expected_direct_scopes(doc: dict[str, Any]) -> dict[str, str]:
    """Declared scope of every root dependency that has a ``node_modules/<name>`` entry."""
    root = doc["packages"][""]
    runtime = set(root.get("dependencies", {}))
    runtime |= set(root.get("optionalDependencies", {}))
    runtime |= set(root.get("peerDependencies", {}))
    declared = runtime | set(root.get("devDependencies", {}))
    out: dict[str, str] = {}
    for name in declared:
        entry = doc["packages"].get(NODE_MODULES + name)
        if entry is None or entry.get("link"):
            continue
        out[entry_key(NODE_MODULES + name, entry)] = "runtime" if name in runtime else "dev"
    return out


def syft_root_children(bom: dict[str, Any]) -> set[str]:
    """Package keys of the direct children of the Syft root (the one unreferenced ref)."""
    referenced = {t for d in bom["dependencies"] for t in d.get("dependsOn", [])}
    (root,) = {d["ref"] for d in bom["dependencies"]} - referenced
    by_ref = {c["bom-ref"]: c for c in bom["components"]}
    (entry,) = [d for d in bom["dependencies"] if d["ref"] == root]
    return {package_key(parse_purl(by_ref[r]["purl"])) for r in entry["dependsOn"]}


def syft_node_keys(bom: dict[str, Any]) -> set[str]:
    """Package keys of every Syft library component except the project root."""
    referenced = {t for d in bom["dependencies"] for t in d.get("dependsOn", [])}
    (root,) = {d["ref"] for d in bom["dependencies"]} - referenced
    return {
        package_key(parse_purl(c["purl"]))
        for c in bom["components"]
        if c["type"] == "library" and c["bom-ref"] != root
    }


def codes(result: ScopeResult) -> list[str]:
    return [w.code for w in result.warnings]


def subjects(result: ScopeResult, code: str) -> list[tuple[str, ...]]:
    return [w.subjects for w in result.warnings if w.code == code]


# --- DG-EX-18 / DG-EX-19: real fixtures ------------------------------------


def test_lock_npm_all_runtime_and_covers_syft_nodes() -> None:
    text = read("lock_npm.json")
    doc = json.loads(text)
    result = parse_package_lock(text)

    expected = expected_package_scopes(doc)
    assert set(expected.values()) == {"runtime"}  # the fixture has no dev flag
    assert dict(result.package_scopes) == expected
    assert len(result.package_scopes) == 115  # 116 entries minus the root

    bom = json.loads(read("syft_npm.cdx.json"))
    assert syft_node_keys(bom) <= set(result.package_scopes)
    assert result.warnings == ()


def test_lock_npm_direct_scopes_match_syft_root_children() -> None:
    text = read("lock_npm.json")
    doc = json.loads(text)
    result = parse_package_lock(text)

    assert dict(result.direct_scopes) == expected_direct_scopes(doc)
    assert set(result.direct_scopes.values()) == {"runtime"}
    declared = {
        npm_key(n, doc["packages"][NODE_MODULES + n]["version"])
        for n in ("express", "JSONStream", "moment", "request")
    }
    assert set(result.direct_scopes) == declared
    # Parity: every direct dependency of the Syft root is a key of direct_scopes.
    assert syft_root_children(json.loads(read("syft_npm.cdx.json"))) <= set(result.direct_scopes)


def test_lock_npm_dev_per_package_scopes() -> None:
    text = read("lock_npm_dev.json")
    doc = json.loads(text)
    result = parse_package_lock(text)

    assert dict(result.package_scopes) == expected_package_scopes(doc)
    assert dict(result.package_scopes) == {
        npm_key("is-number", "7.0.0"): "dev",
        npm_key("left-pad", "1.3.0"): "runtime",
        npm_key("uuid", "3.4.0"): "runtime",  # optional does not make a package dev
    }
    # The expectation really is derived from the file's own flags.
    assert doc["packages"]["node_modules/uuid"]["optional"] is True
    assert doc["packages"]["node_modules/is-number"]["dev"] is True


def test_lock_npm_dev_direct_scopes_and_no_warnings() -> None:
    text = read("lock_npm_dev.json")
    doc = json.loads(text)
    result = parse_package_lock(text)

    assert dict(result.direct_scopes) == expected_direct_scopes(doc)
    assert dict(result.direct_scopes) == {
        npm_key("is-number", "7.0.0"): "dev",
        npm_key("left-pad", "1.3.0"): "runtime",
        npm_key("uuid", "3.4.0"): "runtime",  # optionalDependencies is declared runtime
    }
    assert result.warnings == ()


# --- DG-EX-18 / DG-EX-19: synthetic edge fixture ---------------------------

EDGE_TEXT = read("lock_npm_edge.json")

DEBUG = npm_key("debug", "4.3.4")
CHALK = npm_key("chalk", "4.1.2")
LEFT_PAD = npm_key("left-pad", "1.3.0")
STRING_WIDTH = npm_key("string-width", "4.2.3")
TSLIB = npm_key("tslib", "2.6.2")
ESTREE = npm_key("@types/estree", "1.0.5")


def test_edge_whole_file_expectations() -> None:
    result = parse_package_lock(EDGE_TEXT)
    runtime = {
        CHALK,
        LEFT_PAD,
        npm_key("ora", "5.4.1"),
        npm_key("picomatch", "2.3.1"),
        npm_key("react", "18.2.0"),
        npm_key("rollup", "4.9.6"),
        npm_key("semver", "7.5.4"),
        STRING_WIDTH,
        TSLIB,
        ESTREE,
    }
    assert dict(result.package_scopes) == {**dict.fromkeys(runtime, "runtime"), DEBUG: "dev"}
    assert dict(result.direct_scopes) == {
        CHALK: "dev",
        DEBUG: "runtime",
        LEFT_PAD: "runtime",
        STRING_WIDTH: "runtime",
        TSLIB: "runtime",
    }
    assert sorted(codes(result)) == ["DIRECT_UNRESOLVED", "SCOPE_DISAGREEMENT"]
    assert all(w.service is None for w in result.warnings)
    assert all(w.code in WARNING_CODES for w in result.warnings)
    # Maps iterate in sorted key order (deterministic output).
    assert list(result.package_scopes) == sorted(result.package_scopes)
    assert list(result.direct_scopes) == sorted(result.direct_scopes)


@pytest.mark.parametrize(
    ("key", "scope"),
    [
        pytest.param(npm_key("picomatch", "2.3.1"), "runtime", id="devOptional-is-runtime"),
        pytest.param(npm_key("react", "18.2.0"), "runtime", id="peer-is-runtime"),
        pytest.param(ESTREE, "runtime", id="nested-scoped-name-from-last-segment"),
        pytest.param(STRING_WIDTH, "runtime", id="alias-uses-name-field"),
        pytest.param(npm_key("semver", "7.5.4"), "runtime", id="dev-copy-plus-runtime-copy"),
        pytest.param(DEBUG, "dev", id="runtime-declaration-flagged-dev"),
    ],
)
def test_edge_package_scope_cases(key: str, scope: str) -> None:
    assert parse_package_lock(EDGE_TEXT).package_scopes[key] == scope


def test_edge_link_workspace_and_alias_path_are_not_keys() -> None:
    result = parse_package_lock(EDGE_TEXT)
    for key in (*result.package_scopes, *result.direct_scopes):
        assert "local-lib" not in key  # link entry and packages/local-lib source
        assert "string-width-cjs" not in key  # alias path name never becomes a key
    assert "LOCKFILE_ENTRY_SKIPPED" not in codes(result)  # skipped silently


@pytest.mark.parametrize(
    ("key", "scope"),
    [
        pytest.param(LEFT_PAD, "runtime", id="dependencies"),
        pytest.param(STRING_WIDTH, "runtime", id="alias-declared-by-alias-path"),
        pytest.param(TSLIB, "runtime", id="in-both-groups-is-runtime"),
        pytest.param(CHALK, "dev", id="dev-only-declaration"),
        pytest.param(DEBUG, "runtime", id="declaration-wins-over-dev-flag"),
    ],
)
def test_edge_direct_scope_cases(key: str, scope: str) -> None:
    assert parse_package_lock(EDGE_TEXT).direct_scopes[key] == scope


def test_edge_unresolved_declared_name() -> None:
    result = parse_package_lock(EDGE_TEXT)
    assert subjects(result, "DIRECT_UNRESOLVED") == [("ms",)]
    assert not any("/ms@" in k for k in (*result.package_scopes, *result.direct_scopes))


def test_edge_single_scope_disagreement_for_runtime_declared_dev_flagged() -> None:
    result = parse_package_lock(EDGE_TEXT)
    (warning,) = [w for w in result.warnings if w.code == "SCOPE_DISAGREEMENT"]
    assert warning.subjects == (DEBUG,)
    assert "runtime" in warning.detail
    assert "dev" in warning.detail
    assert result.direct_scopes[DEBUG] == "runtime"  # declaration wins
    assert result.package_scopes[DEBUG] == "dev"


def test_edge_dev_declared_but_runtime_entry_is_silent() -> None:
    result = parse_package_lock(EDGE_TEXT)
    assert result.direct_scopes[CHALK] == "dev"
    assert result.package_scopes[CHALK] == "runtime"
    assert all(CHALK not in w.subjects for w in result.warnings)
    assert all("chalk" not in w.detail for w in result.warnings)


def test_edge_build_graph_silent_dev_dependency_is_dev_direct_and_runtime_transitive() -> None:
    """DG-EX-19 last sentence. Deferred to T7: needs ``build_graph``."""
    build = pytest.importorskip(
        "core.graph.build", reason="build_graph arrives in T7; activate and verify this test there"
    )
    from core.graph.model import ServiceInput

    result = parse_package_lock(EDGE_TEXT)
    ora = npm_key("ora", "5.4.1")

    def lib(name: str, version: str) -> dict[str, Any]:
        purl = f"pkg:npm/{name}@{version}"
        return {"bom-ref": purl, "type": "library", "name": name, "purl": purl}

    root = lib("app", "1.0.0")
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "components": [root, lib("chalk", "4.1.2"), lib("ora", "5.4.1")],
        "dependencies": [
            {"ref": root["bom-ref"], "dependsOn": ["pkg:npm/chalk@4.1.2", "pkg:npm/ora@5.4.1"]},
            {"ref": "pkg:npm/ora@5.4.1", "dependsOn": ["pkg:npm/chalk@4.1.2"]},
        ],
    }
    graph = build.build_graph([ServiceInput("svc", bom, result)])
    node = graph.node(CHALK)
    assert node is not None
    assert set(node.path_infos) == {
        PathInfo(runtime=False, direct=True),
        PathInfo(runtime=True, direct=False),
    }
    ora_node = graph.node(ora)
    assert ora_node is not None
    assert ora_node.path_infos == (PathInfo(runtime=True, direct=True),)


# --- inline synthetic cases ------------------------------------------------


def test_runtime_copy_wins_in_either_order() -> None:
    dev = {"version": "1.0.0", "dev": True}
    runtime = {"version": "1.0.0"}
    key = npm_key("a", "1.0.0")
    for packages in (
        {"node_modules/a": dev, "node_modules/x/node_modules/a": runtime},
        {"node_modules/a": runtime, "node_modules/x/node_modules/a": dev},
    ):
        assert parse_package_lock(lock_text(packages)).package_scopes[key] == "runtime"


def test_peer_and_optional_declarations_are_runtime() -> None:
    text = lock_text(
        {
            "": {"peerDependencies": {"p": "1.0.0"}, "optionalDependencies": {"o": "1.0.0"}},
            "node_modules/p": {"version": "1.0.0", "dev": True},
            "node_modules/o": {"version": "1.0.0", "dev": True},
        }
    )
    result = parse_package_lock(text)
    assert dict(result.direct_scopes) == {
        npm_key("o", "1.0.0"): "runtime",
        npm_key("p", "1.0.0"): "runtime",
    }
    assert sorted(w.subjects[0] for w in result.warnings if w.code == "SCOPE_DISAGREEMENT") == [
        npm_key("o", "1.0.0"),
        npm_key("p", "1.0.0"),
    ]


def test_declared_name_resolving_to_link_is_unresolved() -> None:
    text = lock_text(
        {
            "": {"dependencies": {"local-lib": "file:packages/local-lib"}},
            "node_modules/local-lib": {"resolved": "packages/local-lib", "link": True},
        }
    )
    result = parse_package_lock(text)
    assert subjects(result, "DIRECT_UNRESOLVED") == [("local-lib",)]
    assert dict(result.direct_scopes) == {}


def test_missing_root_entry_gives_empty_direct_scopes_and_no_warning() -> None:
    result = parse_package_lock(lock_text({"node_modules/a": {"version": "1.0.0"}}))
    assert dict(result.direct_scopes) == {}
    assert dict(result.package_scopes) == {npm_key("a", "1.0.0"): "runtime"}
    assert result.warnings == ()


@pytest.mark.parametrize(
    "packages",
    [
        pytest.param({}, id="no-entries"),
        pytest.param({"": {"name": "app", "version": "1.0.0"}}, id="root-only"),
    ],
)
def test_empty_packages(packages: dict[str, Any]) -> None:
    result = parse_package_lock(lock_text(packages))
    assert dict(result.package_scopes) == {}
    assert dict(result.direct_scopes) == {}
    assert result.warnings == ()


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("node_modules/bad name", id="space"),
        pytest.param("node_modules/@scope", id="scope-without-name"),
        pytest.param("node_modules/@scope/", id="scope-empty-name"),
        pytest.param("node_modules/x/node_modules/a/b", id="slash-in-name"),
    ],
)
def test_unpurlable_name_is_skipped_with_warning(path: str) -> None:
    text = lock_text(
        {
            "": {},
            path: {"version": "1.0.0"},
            "node_modules/good": {"version": "2.0.0"},
        }
    )
    result = parse_package_lock(text)
    assert dict(result.package_scopes) == {npm_key("good", "2.0.0"): "runtime"}
    (warning,) = result.warnings
    assert warning.code == "LOCKFILE_ENTRY_SKIPPED"
    assert warning.subjects == (path,)
    assert warning.service is None


def test_unpurlable_alias_name_is_skipped_with_warning() -> None:
    text = lock_text({"node_modules/ok": {"name": "not valid", "version": "1.0.0"}})
    result = parse_package_lock(text)
    assert dict(result.package_scopes) == {}
    assert codes(result) == ["LOCKFILE_ENTRY_SKIPPED"]
    assert result.warnings[0].subjects == ("node_modules/ok",)


# --- DG-SCP-0 / DG-SCP-1: rejections ---------------------------------------


def test_lockfile_v1_is_rejected() -> None:
    v1 = json.dumps(
        {
            "name": "old",
            "lockfileVersion": 1,
            "requires": True,
            "dependencies": {"a": {"version": "1.0.0", "resolved": "https://x/a.tgz"}},
        }
    )
    with pytest.raises(ValueError, match="version 1 is unsupported"):
        parse_package_lock(v1)


@pytest.mark.parametrize("text", ["[]", "null", "1", '"packages"', '{"packages": []}'])
def test_non_lockfile_json_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="packages"):
        parse_package_lock(text)


@pytest.mark.parametrize("text", ["", "{", "not json", '{"packages": {},}', "\x00"])
def test_invalid_json_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_package_lock(text)


def test_oversize_text_is_rejected_before_parsing() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        parse_package_lock(" " * (MAX_LOCKFILE_CHARS + 1))


def test_deeply_nested_json_is_value_error() -> None:
    with pytest.raises(ValueError, match="nesting too deep"):
        parse_package_lock("[" * 100_000)


# --- scopes_common helpers -------------------------------------------------


def test_check_size_boundary_and_type() -> None:
    check_size("x" * MAX_LOCKFILE_CHARS)  # exactly at the limit is accepted
    with pytest.raises(ValueError, match="exceeds"):
        check_size("x" * (MAX_LOCKFILE_CHARS + 1))
    with pytest.raises(ValueError, match="must be str"):
        check_size(b"{}")


def test_load_json_wraps_decoder_failures() -> None:
    assert load_json('{"a": [1]}') == {"a": [1]}
    with pytest.raises(ValueError, match="invalid JSON"):
        load_json("{")
    with pytest.raises(ValueError, match="nesting too deep"):
        load_json("[" * 100_000)


def test_cross_check_fires_only_for_runtime_declared_dev_package() -> None:
    direct: dict[str, Scope] = {
        "npm/a@1": "runtime",
        "npm/b@1": "dev",
        "npm/c@1": "runtime",
        "npm/d@1": "dev",
    }
    packages: dict[str, Scope] = {
        "npm/a@1": "dev",
        "npm/b@1": "runtime",
        "npm/c@1": "runtime",
        "npm/d@1": "dev",
    }
    warnings = cross_check(direct, packages)
    assert [(w.code, w.subjects) for w in warnings] == [("SCOPE_DISAGREEMENT", ("npm/a@1",))]


def test_cross_check_ignores_unknown_keys_and_sorts_output() -> None:
    direct: dict[str, Scope] = {"npm/z@1": "runtime", "npm/m@1": "runtime", "npm/gone@1": "runtime"}
    packages: dict[str, Scope] = {"npm/z@1": "dev", "npm/m@1": "dev"}
    warnings = cross_check(direct, packages)
    assert [w.subjects for w in warnings] == [("npm/m@1",), ("npm/z@1",)]
    assert cross_check({}, {}) == []
