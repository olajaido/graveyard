import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from cli.errors import CliError
from cli.model import ServiceDir
from core.scan.errors import INVALID_INPUT, SBOM_FAILED, SBOM_INVALID, TOO_MANY_PACKAGES
from scan import store
from workflow import graph, syft
from workflow.tests.support import SCAN_ID, make_deps, queued_scan

SPIKES = Path(__file__).resolve().parents[3] / "spikes"
LOCK = SPIKES / "fixtures" / "npm" / "package-lock.json"
SBOM = SPIKES / "npm-sbom.cdx.json"
LIMITS = {"max_purls": 2000}


def seed(deps_artefacts: Any, lock: bytes | None = None) -> None:
    services = [{"index": 0, "path": ".", "files": [{"name": "package-lock.json"}]}]
    deps_artefacts.put(store.services_key(SCAN_ID), json.dumps(services).encode())
    deps_artefacts.put(
        store.manifest_key(SCAN_ID, 0, "package-lock.json"), lock or LOCK.read_bytes()
    )


def test_syft_handler_calls_run_syft_and_stores_the_sbom(tmp_path: Path) -> None:
    deps, table, artefacts, _ = make_deps()
    queued_scan(table)
    seed(artefacts)
    seen: dict[str, Any] = {}

    def fake(
        exe: str, service: ServiceDir, others: Sequence[str], timeout: float, env: Mapping[str, str]
    ) -> dict[str, Any]:
        seen.update(
            exe=exe,
            names=service.lockfiles,
            files=sorted(p.name for p in service.directory.iterdir()),
            others=list(others),
            work=service.directory,
        )
        return {"bomFormat": "CycloneDX", "components": []}

    out = syft.run(
        {"scanId": SCAN_ID, "index": 0},
        deps,
        exe="/opt/bin/syft",
        syft=fake,
        version=lambda e, v: "1.56.0",
    )
    assert out == {"index": 0, "sbomKey": f"scans/{SCAN_ID}/sbom/0.cdx.json"}
    assert seen["exe"] == "/opt/bin/syft" and seen["files"] == ["package-lock.json"]
    assert not seen["work"].exists()  # cleaned up
    assert json.loads(artefacts.objects[out["sbomKey"]])["bomFormat"] == "CycloneDX"


def test_syft_failure_is_a_fixed_error_and_cleans_up() -> None:
    deps, table, artefacts, _ = make_deps()
    queued_scan(table)
    seed(artefacts)
    dirs: list[Path] = []

    def fail(exe: str, service: ServiceDir, *a: Any) -> dict[str, Any]:
        dirs.append(service.directory)
        raise CliError("Syft failed for service '.'")

    with pytest.raises(SBOM_FAILED):
        syft.run({"scanId": SCAN_ID, "index": 0}, deps, syft=fail, version=lambda e, v: "1.56.0")
    assert dirs and not dirs[0].exists()


@pytest.mark.parametrize("index", [-1, 1, "0", True, None])
def test_syft_rejects_bad_index(index: object) -> None:
    deps, table, artefacts, _ = make_deps()
    queued_scan(table)
    seed(artefacts)
    with pytest.raises(INVALID_INPUT):
        syft.run({"scanId": SCAN_ID, "index": index}, deps)


@pytest.mark.syft
@pytest.mark.skipif(shutil.which("syft") is None, reason="Syft 1.56.0 is not installed")
def test_real_syft_binary() -> None:
    exe = shutil.which("syft")
    assert exe is not None
    deps, table, artefacts, _ = make_deps()
    queued_scan(table)
    seed(artefacts)
    try:
        out = syft.run({"scanId": SCAN_ID, "index": 0}, deps, exe=exe)
    except SBOM_FAILED:  # a different Syft version on this machine
        pytest.skip("installed Syft is not 1.56.0")
    bom = json.loads(artefacts.objects[out["sbomKey"]])
    assert len(bom["components"]) > 50


def graph_deps(lock: bytes | None = None, sbom: bytes | None = None):  # type: ignore[no-untyped-def]
    deps, table, artefacts, _ = make_deps()
    queued_scan(table)
    seed(artefacts, lock)
    artefacts.put(store.sbom_key(SCAN_ID, 0), sbom or SBOM.read_bytes())
    return deps, artefacts


def test_graph_writes_purls_and_nodes() -> None:
    deps, artefacts = graph_deps()
    out = graph.run({"scanId": SCAN_ID, "limits": LIMITS}, deps)
    purls = json.loads(artefacts.objects[out["purlsKey"]])
    nodes = json.loads(artefacts.objects[out["nodesKey"]])
    assert out["total"] == len(purls) > 100 and purls == sorted(set(purls))
    assert out["asOf"] == "2025-11-13"
    assert len(nodes["nodes"]) == len(purls)
    assert {"key", "purl", "manifests", "path_infos", "services_affected"} <= set(nodes["nodes"][0])
    assert any(
        not n["path_infos"][0]["direct"] for n in nodes["nodes"] if n["path_infos"]
    )  # a transitive one


def test_graph_limits_and_bad_sbom() -> None:
    deps, _ = graph_deps()
    with pytest.raises(TOO_MANY_PACKAGES):
        graph.run({"scanId": SCAN_ID, "limits": {"max_purls": 5}}, deps)
    deps, _ = graph_deps(sbom=b"not json")
    with pytest.raises(SBOM_INVALID):
        graph.run({"scanId": SCAN_ID, "limits": LIMITS}, deps)
    deps, _ = graph_deps(sbom=b"[]")
    with pytest.raises(SBOM_INVALID):
        graph.run({"scanId": SCAN_ID, "limits": LIMITS}, deps)
    with pytest.raises(INVALID_INPUT):
        graph.run({"scanId": SCAN_ID}, deps)


def test_graph_reads_dev_scope_from_the_lockfile() -> None:
    lock = json.loads(LOCK.read_text())
    root = lock["packages"][""]
    name = sorted(root["dependencies"])[0]
    root.setdefault("devDependencies", {})[name] = root["dependencies"].pop(name)
    lock["packages"][f"node_modules/{name}"]["dev"] = True
    deps, artefacts = graph_deps(lock=json.dumps(lock).encode())
    out = graph.run({"scanId": SCAN_ID, "limits": LIMITS}, deps)
    nodes = json.loads(artefacts.objects[out["nodesKey"]])["nodes"]
    assert any(not p["runtime"] for n in nodes for p in n["path_infos"])
