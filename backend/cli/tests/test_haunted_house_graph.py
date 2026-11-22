"""Regression tests on the demo repository (scan-backend design §17).

The first dev scan of olajaido/haunted-house (content: demo/haunted-house/) marked about 45
npm packages direct, warned MULTIPLE_ROOTS and dropped tslint. The lockfile is the source of
truth for the direct dependencies: 9 runtime and 1 dev (tslint), one root per service.

The SBOMs are Syft 1.56.0 output for demo/haunted-house, recorded once with the absolute path
replaced by /haunted-house and the ``cpe`` fields and ``syft:cpe23`` properties removed: the
graph does not read them, and ``a:\\@babel`` trips the absolute-path check of
test_fixture_project. The last test runs the real binary when it is installed.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Final

import pytest

from cli.discover import find_services
from cli.lockfiles import read_scopes
from cli.model import ServiceDir
from cli.pipeline import augment_service
from core.graph import DependencyGraph, ServiceInput, build_graph

REPO: Final = Path(__file__).resolve().parents[3]
DEMO: Final = REPO / "demo" / "haunted-house"
SBOMS: Final = Path(__file__).resolve().parent / "fixtures" / "sboms"
RECORDED: Final = {
    ".": SBOMS / "haunted-house-npm.cdx.json",
    "services/worker": SBOMS / "haunted-house-worker.cdx.json",
}
NPM_DIRECT: Final = {
    "pkg:npm/axios@1.21.1": True,
    "pkg:npm/coffee-script@1.12.7": True,
    "pkg:npm/command-line-args@6.0.2": True,
    "pkg:npm/commander@15.1.0": True,
    "pkg:npm/gulp-util@3.0.8": True,
    "pkg:npm/material-design-lite@1.3.0": True,
    "pkg:npm/querystring@0.2.1": True,
    "pkg:npm/request-promise@4.2.6": True,
    "pkg:npm/serializr@3.0.5": True,
    "pkg:npm/tslint@6.1.3": False,  # the value is "runtime": tslint is a devDependency
}
PYPI_DIRECT: Final = {
    "pkg:pypi/appdirs@1.4.4",
    "pkg:pypi/argparse@1.4.0",
    "pkg:pypi/attrs@26.1.0",
    "pkg:pypi/eventlet@0.41.3",
    "pkg:pypi/flask-script@2.0.6",
    "pkg:pypi/flask@3.1.3",
    "pkg:pypi/requests@2.34.2",
    "pkg:pypi/typed-ast@1.5.5",
}


def _graph(boms: dict[str, Any]) -> DependencyGraph:
    inputs = []
    for service in find_services(DEMO):
        scopes, _warnings, _used = read_scopes(service)
        bom, _added, _cli_warnings = augment_service(service.path, boms[service.path], scopes)
        inputs.append(ServiceInput(path=service.path, bom=bom, scopes=scopes))
    return build_graph(inputs)


def _recorded() -> DependencyGraph:
    return _graph({path: json.loads(f.read_text()) for path, f in RECORDED.items()})


def _direct(graph: DependencyGraph, service: str) -> dict[str, bool]:
    """Direct purls of one service -> True when a direct path is runtime."""
    return {
        node.purl: any(p.runtime for p in node.path_infos if p.direct)
        for node in graph.nodes
        if service in node.manifests and any(p.direct for p in node.path_infos)
    }


def test_the_npm_service_has_exactly_the_ten_declared_direct_dependencies() -> None:
    assert _direct(_recorded(), ".") == NPM_DIRECT


def test_the_python_service_is_unchanged_with_eight_direct_dependencies() -> None:
    assert set(_direct(_recorded(), "services/worker")) == PYPI_DIRECT


def test_one_root_per_service_and_no_root_warning() -> None:
    codes = {w.code for w in _recorded().warnings}
    assert "MULTIPLE_ROOTS" not in codes
    assert "ROOT_NOT_FOUND" not in codes


def test_tslint_is_present_with_dev_scope_and_its_tree_stays_dev() -> None:
    nodes = {n.purl: n for n in _recorded().nodes}
    tslint = nodes["pkg:npm/tslint@6.1.3"]
    assert [(p.runtime, p.direct) for p in tslint.path_infos] == [(False, True)]
    # Reached only through tslint: dev. typescript is tslint's peer.
    for purl in ("pkg:npm/typescript@7.0.2", "pkg:npm/commander@2.20.3", "pkg:npm/tsutils@2.29.0"):
        assert all(not p.runtime and not p.direct for p in nodes[purl].path_infos), purl


def test_resolved_peers_are_transitive_unless_declared() -> None:
    nodes = {n.purl: n for n in _recorded().nodes}
    request = nodes["pkg:npm/request@2.88.2"]  # peer of request-promise, not in package.json
    assert request.path_infos and all(not p.direct for p in request.path_infos)
    assert any(p.runtime for p in request.path_infos)
    for purl in ("pkg:npm/tunnel-agent@0.6.0", "pkg:npm/har-validator@5.1.5"):
        assert all(not p.direct for p in nodes[purl].path_infos), purl


def test_every_lockfile_package_and_requirement_is_a_node() -> None:
    graph = _recorded()
    lock = json.loads((DEMO / "package-lock.json").read_text())["packages"]
    npm = {f"{k.split('node_modules/')[-1]}@{v['version']}" for k, v in lock.items() if k}
    in_graph = {n.purl.removeprefix("pkg:npm/").replace("%40", "@") for n in graph.nodes}
    assert npm <= in_graph
    assert len(graph.nodes) == len(npm) + len(PYPI_DIRECT)


@pytest.mark.syft
@pytest.mark.skipif(shutil.which("syft") is None, reason="Syft 1.56.0 is not installed")
def test_the_same_result_with_the_real_syft_binary() -> None:
    from cli.syft import check_version, locate_syft, run_syft, syft_environment

    exe = locate_syft(None)
    env = syft_environment(dict(os.environ))
    if check_version(exe, env) != "1.56.0":  # pragma: no cover - other Syft releases
        pytest.skip("installed Syft is not 1.56.0")
    services: list[ServiceDir] = list(find_services(DEMO))
    boms = {s.path: run_syft(exe, s, [x.path for x in services], 120, env) for s in services}
    graph = _graph(boms)
    assert _direct(graph, ".") == NPM_DIRECT
    assert set(_direct(graph, "services/worker")) == PYPI_DIRECT
    assert "MULTIPLE_ROOTS" not in {w.code for w in graph.warnings}
