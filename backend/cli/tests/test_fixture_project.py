"""Integrity and self-check of the anchors fixture project (CLI-TEST-2; design §9.1, §9.2).

The SBOMs are real Syft 1.56.0 output (CLI-FIX-1), so the graphs are built through
``cli.augment.add_direct_edges``, which adds the root -> dev-direct edges Syft does not emit.
Apart from that pure module only ``core.graph``, ``core.scoring`` and the recorded helpers are
used; the rest of the CLI is not imported.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from cli.augment import add_direct_edges
from core.graph import (
    DependencyGraph,
    ScopeResult,
    ServiceInput,
    build_graph,
    exposure_inputs,
    parse_package_lock,
    parse_uv_lock,
)
from core.scoring import score_package, sort_results
from core.scoring.tests.test_anchors import signals_from_fixture
from core.scoring.types import PathInfo, Signals
from core.sources.tests import recorded as rec

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROJECT = FIXTURES / "anchors-project"
SBOMS = FIXTURES / "sboms"

RT_DIRECT = (PathInfo(runtime=True, direct=True),)
RT_TRANSITIVE = (PathInfo(runtime=True, direct=False),)
DEV_DIRECT = (PathInfo(runtime=False, direct=True),)
DEV_TRANSITIVE = (PathInfo(runtime=False, direct=False),)

# Design §9.2: name -> expected path_infos, in the literal rank order.
EXPECTED_ORDER = (
    "pycrypto",
    "left-pad",
    "request",
    "node-uuid",
    "nose",
    "six",
    "uuid",
    "moment",
    "express",
)
EXPECTED_PATHS = {
    "pycrypto": RT_DIRECT,
    "left-pad": RT_DIRECT,
    "request": DEV_DIRECT,
    "node-uuid": RT_TRANSITIVE,
    "nose": DEV_DIRECT,
    "six": RT_DIRECT,
    "uuid": DEV_TRANSITIVE,
    "moment": RT_DIRECT,
    "express": RT_DIRECT,
}

_FORBIDDEN = re.compile(r"/Users/|/home/|\b[A-Za-z]:[\\/]")


def _fixture_files() -> list[Path]:
    return sorted(p for p in FIXTURES.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def _load(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _augmented(path: str, bom_name: str, scopes: ScopeResult) -> ServiceInput:
    bom = add_direct_edges(_load(SBOMS / bom_name), scopes.direct_scopes).bom
    return ServiceInput(path, bom, scopes)


def _web_input() -> ServiceInput:
    text = (PROJECT / "web" / "package-lock.json").read_text(encoding="utf-8")
    return _augmented("web", "web.cdx.json", parse_package_lock(text))


def _api_input() -> ServiceInput:
    text = (PROJECT / "api" / "uv.lock").read_text(encoding="utf-8")
    return _augmented("api", "api.cdx.json", parse_uv_lock(text))


def _two_service_graph() -> DependencyGraph:
    return build_graph([_web_input(), _api_input()])


def _anchor_purls() -> dict[str, str]:
    return {name: rec.anchor_purl(name) for name in EXPECTED_ORDER}


def _bom_refs(bom: dict[str, Any]) -> Iterator[str]:
    yield bom["metadata"]["component"]["bom-ref"]
    for component in bom.get("components", []):
        yield component["bom-ref"]


def test_no_fixture_contains_an_absolute_path() -> None:
    files = _fixture_files()
    assert files
    for path in files:
        assert not _FORBIDDEN.search(path.read_text(encoding="utf-8")), path


@pytest.mark.parametrize("name", ["web", "api"])
def test_every_dependency_ref_is_a_component_bom_ref(name: str) -> None:
    bom = _load(SBOMS / f"{name}.cdx.json")
    refs = set(_bom_refs(bom))
    for entry in bom.get("dependencies", []):
        assert entry["ref"] in refs, entry["ref"]
        for target in entry.get("dependsOn", []):
            assert target in refs, target


def test_two_service_graph_has_the_nine_anchor_purls_and_no_warnings() -> None:
    graph = _two_service_graph()
    assert sorted(n.purl for n in graph.nodes) == sorted(_anchor_purls().values())
    assert graph.warnings == ()


def test_two_service_graph_matches_design_section_9_2() -> None:
    graph = _two_service_graph()
    by_purl = {n.purl: n for n in graph.nodes}
    for name, expected in EXPECTED_PATHS.items():
        node = by_purl[rec.anchor_purl(name)]
        assert node.path_infos == expected, (name, node.path_infos, expected)
        assert node.services_affected == 1, name


@pytest.mark.parametrize("name", ["web", "api"])
def test_the_sboms_are_real_syft_1_56_0_output(name: str) -> None:
    bom = _load(SBOMS / f"{name}.cdx.json")
    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.7"
    [tool] = bom["metadata"]["tools"]["components"]
    assert (tool["name"], tool["version"]) == ("syft", "1.56.0")
    assert bom["metadata"]["component"]["name"] == f"fixtures/{name}"  # the one scrubbed value


def test_the_real_sboms_do_not_link_the_root_to_its_dev_directs() -> None:
    """What the augmentation exists for (docs/SPIKES.md, Q7)."""
    for name, dev in (("web", "request"), ("api", "nose")):
        bom = _load(SBOMS / f"{name}.cdx.json")
        components = {c["bom-ref"]: c["name"] for c in bom["components"] if c["type"] == "library"}
        assert dev in components.values()  # dev dependencies are included (the Syft variable)
        linked = {t for e in bom["dependencies"] for t in e.get("dependsOn", [])}
        assert dev not in {components.get(t) for t in linked if t in components}


def test_the_combined_sbom_is_gone() -> None:
    assert not (SBOMS / "all.cdx.json").exists()


def test_exposure_changes_the_rank_order_to_the_design_literal() -> None:
    graph = _two_service_graph()
    by_purl = {n.purl: n for n in graph.nodes}
    base: dict[str, Signals] = {
        name: signals_from_fixture(rec.anchor_fixture(name)) for name in EXPECTED_ORDER
    }

    with_exposure = []
    for name, signals in base.items():
        paths, affected = exposure_inputs(by_purl[rec.anchor_purl(name)])
        with_exposure.append(
            score_package(dataclasses.replace(signals, paths=paths, services_affected=affected))
        )
    assumed = [score_package(dataclasses.replace(s, paths=None)) for s in base.values()]

    want = [rec.anchor_purl(name) for name in EXPECTED_ORDER]
    got = [r.purl for r in sort_results(with_exposure)]
    assumed_order = [r.purl for r in sort_results(assumed)]
    assert got == want
    assert got != assumed_order
