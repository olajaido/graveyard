"""Unit tests for CycloneDX ingest (DG-ING-1…10, DG-ROOT-1…5, DG-DUP-1…5, DG-WARN-*).

Covers DG-EX-4, 5, 11, 12, 13 and 14 plus nested components, spec versions,
DG-ING-3 type errors, and dropped self-edges and root edges. Expectations for
the recorded Syft fixtures are recomputed here from the BOM with plain ``json``
code. Fixtures resolve via ``Path(__file__).parent``.

``build_graph`` does not exist yet (T7), so the two ``build_graph``-level
rejections of DG-EX-12 (duplicate service path, 51 services) are tested with
the T7 parameter-validation tests, not here.
"""

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from core.graph.cyclonedx import IngestLimits, ParsedService, parse_service
from core.graph.diagnostics import finalise_warnings
from core.graph.model import GraphWarning
from core.purl import package_key, parse_purl

FIXTURES = Path(__file__).parent / "fixtures"
BOM_NAMES = ("syft_npm.cdx.json", "syft_py.cdx.json")
SVC = "services/api"
SUFFIX = "?package-id="


# --- helpers ---------------------------------------------------------------


def load(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def lib(ref: str, purl: str | None = None, **extra: Any) -> dict[str, Any]:
    """A library component. ``purl`` defaults to ``ref``."""
    comp: dict[str, Any] = {"bom-ref": ref, "type": "library", "name": ref}
    comp["purl"] = ref if purl is None else purl
    comp.update(extra)
    return comp


def dep(ref: str, *targets: str) -> dict[str, Any]:
    return {"ref": ref, "dependsOn": list(targets)}


def bom(
    components: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    *,
    spec: str = "1.7",
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": spec,
        "components": components,
        "dependencies": dependencies,
    }
    out.update(extra)
    return out


def parse(doc: Any, *, limits: IngestLimits | None = None, path: str = SVC) -> ParsedService:
    return parse_service(path, doc, limits or IngestLimits())


def warn_codes(parsed: ParsedService) -> list[str]:
    return [w.code for w in parsed.warnings]


def warnings_with(parsed: ParsedService, code: str) -> list[GraphWarning]:
    return [w for w in parsed.warnings if w.code == code]


def npm(name: str, version: str = "1.0.0") -> str:
    return f"pkg:npm/{name}@{version}"


def key(name: str, version: str = "1.0.0") -> str:
    return f"npm/{name}@{version}"


def unreferenced_refs(doc: Mapping[str, Any]) -> set[str]:
    referenced = {t for d in doc["dependencies"] for t in d.get("dependsOn", [])}
    return {d["ref"] for d in doc["dependencies"]} - referenced


def reference_model(doc: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Independent ``packages`` (key -> display purl) and ``adj`` for a Syft-shaped BOM.

    Syft shape: one unreferenced entry, which is a component. Display purls
    here have no qualifiers, so the smallest ``purl`` string per key is enough.
    """
    (root_ref,) = unreferenced_refs(doc)
    ref_key: dict[str, str] = {}
    packages: dict[str, str] = {}
    for comp in doc["components"]:
        if "purl" not in comp or comp["bom-ref"] == root_ref:
            continue
        k = package_key(parse_purl(comp["purl"]))
        ref_key[comp["bom-ref"]] = k
        packages[k] = min(packages.get(k, comp["purl"]), comp["purl"])
    adj: dict[str, set[str]] = {}
    for entry in doc["dependencies"]:
        if entry["ref"] == root_ref:
            continue
        for target in entry.get("dependsOn", []):
            if ref_key[entry["ref"]] != ref_key[target]:
                adj.setdefault(ref_key[entry["ref"]], set()).add(ref_key[target])
    return packages, adj


def adj_as_sets(parsed: ParsedService) -> dict[str, set[str]]:
    return {k: set(v) for k, v in parsed.adj.items()}


# --- DG-EX-4: bom-ref suffix never matters -----------------------------------


@pytest.mark.parametrize("name", BOM_NAMES)
def test_ex4_keys_equal_package_key_of_purl(name: str) -> None:
    doc = load(name)
    parsed = parse(doc)
    (root_ref,) = unreferenced_refs(doc)
    expected = {
        package_key(parse_purl(c["purl"]))
        for c in doc["components"]
        if c.get("purl", "").startswith(("pkg:npm/", "pkg:pypi/")) and c["bom-ref"] != root_ref
    }
    assert set(parsed.packages) == expected
    assert len(expected) > 5
    assert all("package-id" not in k for k in parsed.packages)
    assert all("package-id" not in p for p in parsed.packages.values())


@pytest.mark.parametrize("name", BOM_NAMES)
def test_ex4_every_suffixed_bom_ref_resolves(name: str) -> None:
    doc = load(name)
    refs = {c["bom-ref"] for c in doc["components"]}
    suffixed = [c for c in doc["components"] if SUFFIX in c["bom-ref"]]
    assert suffixed
    # The bare purl is not a bom-ref (npm: lower-case ref; pypi: ref carries the suffix).
    assert all(c["purl"] not in refs for c in suffixed)
    parsed = parse(doc)
    packages, adj = reference_model(doc)
    assert dict(parsed.packages) == packages
    assert adj_as_sets(parsed) == adj
    assert not warnings_with(parsed, "DANGLING_REF")


@pytest.mark.parametrize("name", BOM_NAMES)
def test_ex4_rewriting_suffix_hashes_changes_nothing(name: str) -> None:
    doc = load(name)
    text = json.dumps(doc)
    hashes = {
        ref.split(SUFFIX)[1] for ref in (c["bom-ref"] for c in doc["components"]) if SUFFIX in ref
    }
    for i, h in enumerate(sorted(hashes)):
        text = text.replace(h, f"{i:016x}")
    assert text != json.dumps(doc)
    assert parse(json.loads(text)) == parse(doc)


def test_ex4_suffix_is_opaque_so_a_different_suffix_does_not_resolve() -> None:
    doc = bom(
        [lib(npm("a") + SUFFIX + "aaa", npm("a")), lib(npm("b") + SUFFIX + "bbb", npm("b"))],
        [dep(npm("a") + SUFFIX + "aaa", npm("b") + SUFFIX + "OTHER")],
    )
    parsed = parse(doc)
    assert [w.subjects for w in warnings_with(parsed, "DANGLING_REF")] == [
        (npm("b") + SUFFIX + "OTHER",)
    ]
    assert dict(parsed.adj) == {}


def test_ex4_components_differing_only_in_suffix_are_one_package() -> None:
    doc = bom(
        [
            lib("root"),
            lib(npm("a") + SUFFIX + "1", npm("a")),
            lib(npm("a") + SUFFIX + "2", npm("a")),
            lib(npm("b")),
        ],
        [
            dep("root", npm("a") + SUFFIX + "1", npm("a") + SUFFIX + "2"),
            dep(npm("a") + SUFFIX + "2", npm("b")),
        ],
    )
    doc["components"][0]["purl"] = npm("root")
    parsed = parse(doc)
    assert set(parsed.packages) == {key("a"), key("b")}
    assert parsed.directs == (key("a"),)
    assert adj_as_sets(parsed) == {key("a"): {key("b")}}


# --- DG-EX-5: case fold ------------------------------------------------------


def _jsonstream(doc: Mapping[str, Any]) -> dict[str, Any]:
    (comp,) = (c for c in doc["components"] if c.get("purl") == "pkg:npm/JSONStream@1.3.5")
    assert isinstance(comp, dict)
    return comp


def test_ex5_recorded_fixture_folds_case_in_key_and_keeps_it_in_purl() -> None:
    doc = load("syft_npm.cdx.json")
    comp = _jsonstream(doc)
    assert comp["bom-ref"].startswith("pkg:npm/jsonstream@1.3.5" + SUFFIX)
    parsed = parse(doc)
    assert parsed.packages["npm/jsonstream@1.3.5"] == "pkg:npm/JSONStream@1.3.5"
    assert "npm/JSONStream@1.3.5" not in parsed.packages
    assert "npm/jsonstream@1.3.5" in parsed.directs


def _with_second_jsonstream(order_reversed: bool) -> tuple[dict[str, Any], str]:
    doc = copy.deepcopy(load("syft_npm.cdx.json"))
    (accepts,) = (c for c in doc["components"] if c.get("purl") == "pkg:npm/accepts@1.3.8")
    second_ref = "pkg:npm/jsonstream@1.3.5" + SUFFIX + "ffffffffffffffff"
    second = lib(second_ref, "pkg:npm/jsonstream@1.3.5", name="jsonstream")
    (root_ref,) = unreferenced_refs(doc)
    doc["components"].append(second)
    # The second spelling is reached from the root and has an edge the first lacks.
    next(d for d in doc["dependencies"] if d["ref"] == root_ref)["dependsOn"].append(second_ref)
    doc["dependencies"].append(dep(second_ref, accepts["bom-ref"]))
    if order_reversed:
        doc["components"].reverse()
        doc["dependencies"].reverse()
    return doc, accepts["bom-ref"]


@pytest.mark.parametrize("order_reversed", [False, True])
def test_ex5_second_spelling_merges_into_one_node_with_union_of_edges(
    order_reversed: bool,
) -> None:
    original = load("syft_npm.cdx.json")
    base = parse(original)
    doc, _ = _with_second_jsonstream(order_reversed)
    parsed = parse(doc)
    k = "npm/jsonstream@1.3.5"
    assert set(parsed.packages) == set(base.packages)
    assert sum(1 for p in parsed.packages.values() if p.lower() == "pkg:npm/jsonstream@1.3.5") == 1
    # Smallest display purl wins; upper-case 'J' sorts before 'j'. Order never matters.
    assert parsed.packages[k] == "pkg:npm/JSONStream@1.3.5"
    assert set(parsed.adj[k]) == set(base.adj[k]) | {"npm/accepts@1.3.8"}
    assert parsed.directs == base.directs
    assert not warnings_with(parsed, "MULTIPLE_ROOTS")


def test_ex5_lower_case_only_spelling_has_lower_case_display_purl() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("ref-1", "pkg:npm/jsonstream@1.3.5")],
        [dep("root", "ref-1")],
    )
    parsed = parse(doc)
    assert parsed.packages == {"npm/jsonstream@1.3.5": "pkg:npm/jsonstream@1.3.5"}


# --- DG-DUP: display purl, qualifiers, versions -------------------------------


def test_dup3_display_purl_drops_qualifiers_and_subpath() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("r1", "pkg:pypi/Foo_Bar@1.0?extension=whl#sub")],
        [dep("root", "r1")],
    )
    assert parse(doc).packages == {"pypi/foo-bar@1.0": "pkg:pypi/foo-bar@1.0"}


def test_dup5_different_versions_are_different_nodes() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("r1", npm("a", "1.0.0")), lib("r2", npm("a", "2.0.0"))],
        [dep("root", "r1", "r2")],
    )
    parsed = parse(doc)
    assert set(parsed.packages) == {key("a", "1.0.0"), key("a", "2.0.0")}
    assert parsed.directs == (key("a", "1.0.0"), key("a", "2.0.0"))


def test_dup1_duplicate_component_entries_are_harmless() -> None:
    comp = lib("r1", npm("a"))
    doc = bom(
        [lib("root", npm("app")), comp, copy.deepcopy(comp)],
        [dep("root", "r1", "r1"), dep("root", "r1")],
    )
    parsed = parse(doc)
    assert parsed.directs == (key("a"),)
    assert warn_codes(parsed) == []


def test_multiple_dependencies_entries_for_one_ref_are_unioned() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a")), lib("b", npm("b")), lib("c", npm("c"))],
        [dep("root", "a"), dep("a", "b"), dep("a", "c")],
    )
    assert adj_as_sets(parse(doc)) == {key("a"): {key("b"), key("c")}}


_FOUR = [lib("root", npm("app")), lib("a", npm("a")), lib("b", npm("b")), lib("c", npm("c"))]


@pytest.mark.parametrize(
    "entries",
    [
        [dep("a", "b"), dep("a", "c")],
        [dep("a", "c"), dep("a", "b")],
        # A later entry without targets (or with an empty list) must not erase an earlier one.
        [dep("a", "b"), dep("a", "c"), {"ref": "a"}],
        [dep("a", "b"), dep("a", "c"), dep("a")],
        # Overlapping halves are still the union.
        [dep("a", "b", "c"), dep("a", "c")],
    ],
    ids=["b-then-c", "c-then-b", "trailing-no-dependsOn", "trailing-empty", "overlap"],
)
def test_dup1_one_ref_with_two_entries_has_adj_equal_to_the_union(
    entries: list[dict[str, Any]],
) -> None:
    """DG-DUP-1: two ``dependencies`` entries for one bom-ref merge; none overwrites another."""
    parsed = parse(bom(_FOUR, [dep("root", "a"), *entries]))
    assert adj_as_sets(parsed) == {key("a"): {key("b"), key("c")}}
    assert parsed.directs == (key("a"),)
    assert warn_codes(parsed) == []


def test_dup1_root_with_two_entries_has_the_union_of_children_as_directs() -> None:
    parsed = parse(bom(_FOUR, [dep("root", "a"), dep("root", "b", "c"), dep("a", "b")]))
    assert parsed.directs == (key("a"), key("b"), key("c"))
    assert adj_as_sets(parsed) == {key("a"): {key("b")}}
    assert warnings_with(parsed, "MULTIPLE_ROOTS") == []


def test_dup1_split_entries_across_aliased_refs_still_union_per_package() -> None:
    """Two bom-refs for one package, one with two entries: all three entries contribute edges."""
    doc = bom(
        [*_FOUR, lib("a2", npm("a"))],
        [dep("root", "a", "a2"), dep("a", "b"), dep("a", "c"), dep("a2", "b"), dep("a2", "a")],
    )
    parsed = parse(doc)
    assert adj_as_sets(parsed) == {key("a"): {key("b"), key("c")}}
    assert parsed.directs == (key("a"),)


# --- DG-EX-11: warnings -------------------------------------------------------


def _warning_bom() -> dict[str, Any]:
    return bom(
        [
            lib("root", npm("app")),
            lib("a", npm("a")),
            lib("b", npm("b")),
            lib("mvn", "pkg:maven/org.example/thing@1.0"),
            {"bom-ref": "nolib", "type": "library", "name": "nolib"},
            {"bom-ref": "noapp", "type": "application", "name": "noapp"},
            {"bom-ref": "lockfile", "type": "file", "name": "/package-lock.json"},
        ],
        [dep("root", "a", "mvn", "ghost"), dep("a", "b")],
    )


def test_ex11_warnings_and_rest_of_graph_still_built() -> None:
    parsed = parse(_warning_bom())
    assert set(warn_codes(parsed)) == {"UNSUPPORTED_PURL", "MISSING_PURL", "DANGLING_REF"}
    assert all(w.service == SVC for w in parsed.warnings)
    assert set(parsed.packages) == {key("a"), key("b")}
    assert parsed.directs == (key("a"),)
    assert adj_as_sets(parsed) == {key("a"): {key("b")}}


def test_ex11_unsupported_purl_names_the_type_and_the_component() -> None:
    parsed = parse(_warning_bom())
    (w,) = warnings_with(parsed, "UNSUPPORTED_PURL")
    assert w.subjects == ("mvn",)
    assert "maven" in w.detail


def test_ex11_missing_purl_only_for_library_and_application() -> None:
    parsed = parse(_warning_bom())
    subjects = sorted(s for w in warnings_with(parsed, "MISSING_PURL") for s in w.subjects)
    assert subjects == ["noapp", "nolib"]  # the file component is silent


@pytest.mark.parametrize("kind", ["file", "framework", "data", "container", None])
def test_ex11_other_types_without_purl_are_silent(kind: str | None) -> None:
    comp: dict[str, Any] = {"bom-ref": "x", "name": "x"}
    if kind is not None:
        comp["type"] = kind
    doc = bom([lib("root", npm("app")), lib("a", npm("a")), comp], [dep("root", "a")])
    assert warn_codes(parse(doc)) == []


def test_ex11_dangling_covers_missing_and_skipped_targets() -> None:
    parsed = parse(_warning_bom())
    # 'mvn' was skipped (UNSUPPORTED_PURL) and a target resolving to it is dangling too.
    subjects = [s for w in warnings_with(parsed, "DANGLING_REF") for s in w.subjects]
    assert sorted(subjects) == ["ghost", "mvn"]


def test_ex11_dependencies_entry_for_unknown_ref_is_dangling() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a"))],
        [dep("root", "a"), dep("phantom", "a")],
    )
    parsed = parse(doc)
    (w,) = warnings_with(parsed, "DANGLING_REF")
    assert w.subjects == ("phantom",)
    assert adj_as_sets(parsed) == {}


def test_ex11_unparseable_purl_is_unsupported_not_fatal() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a")), lib("junk", "not-a-purl")],
        [dep("root", "a")],
    )
    parsed = parse(doc)
    assert warn_codes(parsed) == ["UNSUPPORTED_PURL"]
    assert set(parsed.packages) == {key("a")}


def test_warnings_are_finalised_sorted_and_deduplicated() -> None:
    # Two sources point at the same missing ref: one warning, not two.
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a")), lib("b", npm("b"))],
        [dep("root", "a", "b", "ghost"), dep("a", "ghost"), dep("b", "ghost")],
    )
    parsed = parse(doc)
    assert [w.subjects for w in parsed.warnings] == [("ghost",)]
    assert parsed.warnings == finalise_warnings(parsed.warnings)


def test_component_without_bom_ref_is_a_node_but_cannot_be_referenced() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a")), {"type": "library", "purl": npm("z")}],
        [dep("root", "a")],
    )
    parsed = parse(doc)
    assert set(parsed.packages) == {key("a"), key("z")}
    assert warn_codes(parsed) == []


# --- DG-EX-12: rejections -----------------------------------------------------


def _minimal(**overrides: Any) -> dict[str, Any]:
    doc = bom([lib("root", npm("app")), lib("a", npm("a"))], [dep("root", "a")])
    doc.update(overrides)
    return doc


@pytest.mark.parametrize("spec", ["1.4", "2.0", "1.8", "1.7.0", "", 1.7, 1.5, None, ["1.7"]])
def test_ex12_unsupported_or_mistyped_spec_version_raises(spec: Any) -> None:
    with pytest.raises(ValueError, match=rf"^{SVC}: specVersion: "):
        parse(_minimal(specVersion=spec))


def test_ex12_missing_spec_version_raises() -> None:
    doc = _minimal()
    del doc["specVersion"]
    with pytest.raises(ValueError, match=rf"^{SVC}: specVersion: "):
        parse(doc)


@pytest.mark.parametrize("fmt", ["SPDX", "cyclonedx", None, 3])
def test_ex12_wrong_bom_format_raises(fmt: Any) -> None:
    with pytest.raises(ValueError, match=rf"^{SVC}: bomFormat: "):
        parse(_minimal(bomFormat=fmt))


def test_ex12_absent_bom_format_is_accepted() -> None:
    doc = _minimal()
    del doc["bomFormat"]
    assert parse(doc).directs == (key("a"),)


@pytest.mark.parametrize("doc", [[], [{"specVersion": "1.7"}], "text", 7, None])
def test_ex12_non_mapping_bom_raises(doc: Any) -> None:
    with pytest.raises(ValueError, match=rf"^{SVC}: bom: "):
        parse(doc)


def test_ex12_conflicting_duplicate_bom_ref_raises() -> None:
    doc = bom([lib("dup", npm("a")), lib("dup", npm("b"))], [])
    with pytest.raises(ValueError, match=r"bom-ref"):
        parse(doc)


def test_ex12_duplicate_bom_ref_with_one_skipped_component_raises() -> None:
    doc = bom([lib("dup", npm("a")), lib("dup", "pkg:maven/g/a@1")], [])
    with pytest.raises(ValueError, match=r"bom-ref"):
        parse(doc)


def test_ex12_duplicate_bom_ref_with_same_package_is_harmless() -> None:
    doc = bom(
        [
            lib("root", npm("app")),
            lib("dup", "pkg:npm/JSONStream@1.3.5"),
            lib("dup", "pkg:npm/jsonstream@1.3.5"),
        ],
        [dep("root", "dup")],
    )
    parsed = parse(doc)
    assert parsed.directs == ("npm/jsonstream@1.3.5",)
    assert parsed.packages["npm/jsonstream@1.3.5"] == "pkg:npm/JSONStream@1.3.5"


def test_ex12_depends_on_string_raises() -> None:
    doc = bom([lib("root", npm("app"))], [{"ref": "root", "dependsOn": "x"}])
    with pytest.raises(ValueError, match=r"dependencies\[0\]\.dependsOn"):
        parse(doc)


def test_ex12_max_components_counts_nested_components() -> None:
    comps = [lib("a", npm("a"), components=[lib("b", npm("b")), lib("c", npm("c"))])]
    assert len(parse(bom(comps, []), limits=IngestLimits(max_components=3)).packages) == 3
    with pytest.raises(ValueError, match=r"components: more than 2 components"):
        parse(bom(comps, []), limits=IngestLimits(max_components=2))


def test_ex12_max_components_is_checked_while_flattening() -> None:
    comps = [lib(f"r{i}", npm(f"p{i}")) for i in range(11)]
    with pytest.raises(ValueError, match=r"more than 10 components"):
        parse(bom(comps, []), limits=IngestLimits(max_components=10))


def _chain_bom(n_edges: int) -> dict[str, Any]:
    """root -> p0 -> p1 -> ... with ``n_edges`` non-root edges."""
    names = [f"p{i}" for i in range(n_edges + 1)]
    comps = [lib("root", npm("app"))] + [lib(n, npm(n)) for n in names]
    deps = [dep("root", names[0])] + [dep(a, b) for a, b in zip(names, names[1:], strict=False)]
    return bom(comps, deps)


def test_ex12_max_edges_exceeded_raises_and_exact_limit_is_accepted() -> None:
    assert len(parse(_chain_bom(3), limits=IngestLimits(max_edges=3)).adj) == 3
    with pytest.raises(ValueError, match=r"dependencies: more than 2 edges"):
        parse(_chain_bom(3), limits=IngestLimits(max_edges=2))


def test_ex12_max_edges_counts_distinct_edges_only() -> None:
    # Three bom-refs for the same two packages give one distinct edge.
    doc = bom(
        [
            lib("root", npm("app")),
            lib("a1", npm("a")),
            lib("a2", npm("a")),
            lib("b1", npm("b")),
            lib("b2", npm("b")),
        ],
        [dep("root", "a1"), dep("a1", "b1", "b2"), dep("a2", "b1", "b2", "b1")],
    )
    parsed = parse(doc, limits=IngestLimits(max_edges=1))
    assert adj_as_sets(parsed) == {key("a"): {key("b")}}


def test_error_messages_do_not_echo_input_values() -> None:
    secret = "attacker-controlled-value"
    with pytest.raises(ValueError) as info:
        parse(_minimal(specVersion=secret))
    assert secret not in str(info.value)


# --- DG-ING-3: each type error raises ------------------------------------------


def _set(path: str, value: Any) -> dict[str, Any]:
    """A valid BOM with the value at a dotted path replaced (``[i]`` indexes a list)."""
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a"), components=[lib("n", npm("n"))])],
        [dep("root", "a"), dep("a", "n")],
    )
    node: Any = doc
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[int(part)] if part.isdigit() else node[part]
    last = parts[-1]
    if last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value
    return doc


TYPE_ERRORS = [
    ("components", "components", {"x": 1}),
    ("components", "components", None),
    ("components", "components.0", "not-a-mapping"),
    ("components", "components.1", ["list"]),
    ("components[0].bom-ref", "components.0.bom-ref", 5),
    ("components[0].bom-ref", "components.0.bom-ref", ""),
    ("components[0].bom-ref", "components.0.bom-ref", None),
    ("components[0].purl", "components.0.purl", 5),
    ("components[0].purl", "components.0.purl", ["pkg:npm/a@1"]),
    ("components[0].type", "components.0.type", 5),
    ("components[1].components", "components.1.components", "nested"),
    ("components[1].components", "components.1.components", {"a": 1}),
    ("components[1].components[0]", "components.1.components.0", 3),
    ("components[1].components[0].purl", "components.1.components.0.purl", 3),
    ("dependencies", "dependencies", "none"),
    ("dependencies", "dependencies", {"ref": "root"}),
    ("dependencies[0]", "dependencies.0", "root"),
    ("dependencies[0].ref", "dependencies.0.ref", 1),
    ("dependencies[0].ref", "dependencies.0.ref", ""),
    ("dependencies[0].ref", "dependencies.0.ref", None),
    ("dependencies[0].dependsOn", "dependencies.0.dependsOn", "a"),
    ("dependencies[0].dependsOn", "dependencies.0.dependsOn", {"a": 1}),
    ("dependencies[0].dependsOn", "dependencies.0.dependsOn", ["a", 2]),
    ("dependencies[0].dependsOn", "dependencies.0.dependsOn", [["a"]]),
]


@pytest.mark.parametrize(("field", "where", "value"), TYPE_ERRORS)
def test_ing3_wrong_types_raise_naming_service_and_field(
    field: str, where: str, value: Any
) -> None:
    with pytest.raises(ValueError) as info:
        parse(_set(where, value))
    message = str(info.value)
    assert message.startswith(f"{SVC}: ")
    assert field in message


def test_ing3_absent_collections_are_empty_and_unknown_fields_are_ignored() -> None:
    parsed = parse({"specVersion": "1.7", "future": {"anything": [1, 2]}})
    assert dict(parsed.packages) == {}
    assert warn_codes(parsed) == ["ROOT_NOT_FOUND"]
    doc = bom(
        [lib("root", npm("app"), extra=1), lib("a", npm("a"))],
        [{"ref": "root", "dependsOn": ["a"], "unknown": True}, {"ref": "a", "x": 1}],
        vulnerabilities=[{"id": "X"}],
    )
    assert parse(doc).directs == (key("a"),)


def test_ing3_empty_bom_yields_no_packages() -> None:
    parsed = parse(bom([], []))
    assert dict(parsed.packages) == {}
    assert parsed.directs == ()


# --- spec versions, nesting ------------------------------------------------------


@pytest.mark.parametrize("spec", ["1.5", "1.6", "1.7"])
def test_supported_spec_versions_are_accepted(spec: str) -> None:
    doc = bom([lib("root", npm("app")), lib("a", npm("a"))], [dep("root", "a")], spec=spec)
    assert parse(doc).directs == (key("a"),)


def test_nested_components_are_flattened_at_any_depth() -> None:
    deepest = lib("d", npm("d"))
    nested = lib(
        "a",
        npm("a"),
        components=[lib("b", npm("b"), components=[lib("c", npm("c"), components=[deepest])])],
    )
    doc = bom(
        [lib("root", npm("app")), nested],
        [dep("root", "a"), dep("a", "b"), dep("b", "c"), dep("c", "d")],
    )
    parsed = parse(doc)
    assert set(parsed.packages) == {key(x) for x in "abcd"}
    assert adj_as_sets(parsed) == {
        key("a"): {key("b")},
        key("b"): {key("c")},
        key("c"): {key("d")},
    }


def test_deeply_nested_components_do_not_hit_the_recursion_limit() -> None:
    inner: dict[str, Any] = lib("leaf", npm("leaf"))
    for i in range(3000):
        inner = lib(f"n{i}", npm(f"n{i}"), components=[inner])
    parsed = parse(bom([inner], []), limits=IngestLimits(max_components=10_000))
    assert len(parsed.packages) == 3001


def test_nested_component_can_be_the_root() -> None:
    doc = bom(
        [lib("wrapper", npm("wrapper"), components=[lib("root", npm("app"))]), lib("a", npm("a"))],
        [dep("root", "a")],
    )
    parsed = parse(doc)
    assert parsed.directs == (key("a"),)
    assert key("app") not in parsed.packages


# --- self-edges and edges into the root ---------------------------------------------


def test_self_edges_are_dropped_without_warning() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a")), lib("b", npm("b")), lib("b2", npm("b"))],
        [dep("root", "a"), dep("a", "a", "b"), dep("b", "b2")],
    )
    parsed = parse(doc)
    assert parsed.directs == (key("a"),)
    # a->a is a self-edge; b->b2 maps both ends to one key (DG-ING-10, DG-DUP-1).
    assert adj_as_sets(parsed) == {key("a"): {key("b")}}
    assert warn_codes(parsed) == []


def test_entry_listed_in_a_depends_on_is_not_a_root_so_no_edge_targets_a_root() -> None:
    """DG-ING-10 with DG-ROOT-1: an entry listed in any ``dependsOn`` is not a root.

    An edge back to the project component therefore removes its root status
    instead of being dropped: the service has no root, the component is an
    ordinary node and the edges are kept. The ``target in roots`` guard in
    ``parse_service`` is defensive; no input reaches it.
    """
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a"))],
        [dep("root", "a"), dep("a", "root")],
    )
    parsed = parse(doc)
    assert warn_codes(parsed) == ["ROOT_NOT_FOUND"]
    assert parsed.directs == ()
    assert set(parsed.packages) == {key("a"), key("app")}
    assert adj_as_sets(parsed) == {key("a"): {key("app")}, key("app"): {key("a")}}


def test_root_listing_itself_in_depends_on_loses_root_status() -> None:
    doc = bom([lib("root", npm("app")), lib("a", npm("a"))], [dep("root", "a", "root")])
    assert warn_codes(parse(doc)) == ["ROOT_NOT_FOUND"]


# --- DG-EX-13: spec-conformant upload ---------------------------------------------


def _conformant() -> dict[str, Any]:
    return bom(
        [lib("pkg:npm/a@1.0.0"), lib("pkg:npm/b@1.0.0"), lib("pkg:npm/c@1.0.0")],
        [
            dep("root", "pkg:npm/a@1.0.0", "pkg:npm/b@1.0.0"),
            dep("pkg:npm/a@1.0.0", "pkg:npm/c@1.0.0"),
        ],
        metadata={"component": {"bom-ref": "root", "type": "application", "name": "app"}},
    )


def _syft_shaped() -> dict[str, Any]:
    root = "pkg:npm/app@1.0.0" + SUFFIX + "1111111111111111"
    return bom(
        [
            lib(root, "pkg:npm/app@1.0.0"),
            lib("pkg:npm/a@1.0.0" + SUFFIX + "aa", "pkg:npm/a@1.0.0"),
            lib("pkg:npm/b@1.0.0" + SUFFIX + "bb", "pkg:npm/b@1.0.0"),
            lib("pkg:npm/c@1.0.0" + SUFFIX + "cc", "pkg:npm/c@1.0.0"),
        ],
        [
            dep(root, "pkg:npm/a@1.0.0" + SUFFIX + "aa", "pkg:npm/b@1.0.0" + SUFFIX + "bb"),
            dep("pkg:npm/a@1.0.0" + SUFFIX + "aa", "pkg:npm/c@1.0.0" + SUFFIX + "cc"),
        ],
        metadata={"component": {"bom-ref": "dirhash0123456789", "type": "file", "name": "d"}},
    )


def test_ex13_metadata_root_gives_same_graph_as_syft_shaped_root() -> None:
    conformant = parse(_conformant())
    syft = parse(_syft_shaped())
    assert set(conformant.packages) == {key("a"), key("b"), key("c")}
    assert conformant.packages == syft.packages
    assert conformant.directs == syft.directs == (key("a"), key("b"))
    assert conformant.adj == syft.adj
    assert conformant.warnings == syft.warnings == ()


def test_ex13_metadata_root_is_not_a_node_and_not_in_components() -> None:
    doc = _conformant()
    assert all(c["bom-ref"] != "root" for c in doc["components"])
    assert all("root" not in k for k in parse(doc).packages)


def test_ex13_metadata_root_with_no_children_is_still_the_root() -> None:
    doc = bom(
        [lib("a", npm("a"))],
        [dep("root"), dep("a")],
        metadata={"component": {"bom-ref": "root", "type": "application", "name": "app"}},
    )
    parsed = parse(doc)
    assert parsed.directs == ()
    assert set(parsed.packages) == {key("a")}
    assert warn_codes(parsed) == []


@pytest.mark.parametrize("metadata", [None, {}, {"component": None}, {"component": {}}])
def test_absent_or_null_metadata_counts_as_absent(metadata: Any) -> None:
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a"))],
        [dep("root", "a")],
        metadata=metadata,
    )
    parsed = parse(doc)
    assert parsed.directs == (key("a"),)
    assert warn_codes(parsed) == []


# --- DG-EX-14: roots ----------------------------------------------------------------


def test_ex14a_two_unreferenced_entries_are_both_roots() -> None:
    doc = bom(
        [lib("r2", npm("r2")), lib("r1", npm("r1")), lib("a", npm("a")), lib("b", npm("b"))],
        [dep("r2", "b"), dep("r1", "a"), dep("a")],
    )
    parsed = parse(doc)
    assert parsed.directs == (key("a"), key("b"))
    # Both root components leave the node set (documented orphan-library behaviour).
    assert set(parsed.packages) == {key("a"), key("b")}
    (w,) = warnings_with(parsed, "MULTIPLE_ROOTS")
    assert w.subjects == ("r1", "r2")
    assert w.service == SVC
    assert warn_codes(parsed) == ["MULTIPLE_ROOTS"]


def test_ex14a_metadata_root_plus_an_unreferenced_component_with_children() -> None:
    doc = bom(
        [lib("lib", npm("lib")), lib("a", npm("a")), lib("b", npm("b"))],
        [dep("root", "a"), dep("lib", "b")],
        metadata={"component": {"bom-ref": "root", "type": "application", "name": "app"}},
    )
    parsed = parse(doc)
    assert parsed.directs == (key("a"), key("b"))
    assert key("lib") not in parsed.packages
    assert [w.subjects for w in warnings_with(parsed, "MULTIPLE_ROOTS")] == [("lib", "root")]


def test_ex14b_unreferenced_entry_with_empty_depends_on_stays_a_node() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a")), lib("orphan", npm("orphan"))],
        [dep("root", "a"), dep("orphan")],
    )
    parsed = parse(doc)
    assert key("orphan") in parsed.packages
    assert parsed.directs == (key("a"),)
    assert warn_codes(parsed) == []


def test_ex14b_orphan_without_any_entry_and_without_depends_on_key_is_a_node() -> None:
    doc = bom(
        [lib("root", npm("app")), lib("a", npm("a")), lib("o1", npm("o1")), lib("o2", npm("o2"))],
        [dep("root", "a"), {"ref": "o1"}],
    )
    parsed = parse(doc)
    assert {key("o1"), key("o2")} <= set(parsed.packages)
    assert warn_codes(parsed) == []


def test_ex14b_without_a_real_root_the_same_orphan_gives_root_not_found() -> None:
    doc = bom([lib("orphan", npm("orphan"))], [dep("orphan")])
    parsed = parse(doc)
    assert key("orphan") in parsed.packages
    assert warn_codes(parsed) == ["ROOT_NOT_FOUND"]


def test_ex14c_no_root_entry_gives_root_not_found_with_nodes_and_no_directs() -> None:
    doc = bom(
        [lib("a", npm("a")), lib("b", npm("b"))],
        [dep("a", "b"), dep("b", "a")],  # both referenced: nobody is a root
    )
    parsed = parse(doc)
    assert warn_codes(parsed) == ["ROOT_NOT_FOUND"]
    assert set(parsed.packages) == {key("a"), key("b")}
    assert parsed.directs == ()
    assert adj_as_sets(parsed) == {key("a"): {key("b")}, key("b"): {key("a")}}


def test_ex14c_no_dependencies_at_all() -> None:
    parsed = parse(bom([lib("a", npm("a"))], []))
    assert warn_codes(parsed) == ["ROOT_NOT_FOUND"]
    assert parsed.directs == ()
    assert set(parsed.packages) == {key("a")}


def test_root_selection_ignores_component_and_entry_order() -> None:
    doc = bom(
        [lib("r2", npm("r2")), lib("r1", npm("r1")), lib("a", npm("a")), lib("b", npm("b"))],
        [dep("r2", "b"), dep("r1", "a", "b"), dep("a", "b")],
    )
    flipped = copy.deepcopy(doc)
    flipped["components"].reverse()
    flipped["dependencies"].reverse()
    for entry in flipped["dependencies"]:
        entry["dependsOn"].reverse()
    assert parse(doc) == parse(flipped)


# --- recorded fixtures: roots ---------------------------------------------------------


@pytest.mark.parametrize("name", BOM_NAMES)
def test_recorded_fixtures_have_the_project_component_as_root(name: str) -> None:
    doc = load(name)
    parsed = parse(doc)
    (root_ref,) = unreferenced_refs(doc)
    (root_comp,) = (c for c in doc["components"] if c["bom-ref"] == root_ref)
    assert package_key(parse_purl(root_comp["purl"])) not in parsed.packages
    assert "ROOT_NOT_FOUND" not in warn_codes(parsed)
    assert "MULTIPLE_ROOTS" not in warn_codes(parsed)
    # The root's children are the directs.
    (entry,) = (d for d in doc["dependencies"] if d["ref"] == root_ref)
    ref_key = {
        c["bom-ref"]: package_key(parse_purl(c["purl"])) for c in doc["components"] if "purl" in c
    }
    assert parsed.directs == tuple(sorted({ref_key[t] for t in entry["dependsOn"]}))
