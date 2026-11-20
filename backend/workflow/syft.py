"""GenerateSBOM for one service (SB-SBOM-1 to SB-SBOM-5).

Runs the Syft binary of the layer (``/opt/bin/syft``) through the CLI's own ``run_syft``.
Syft only reads the downloaded files; nothing is installed or executed (T9).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from cli.errors import CliError
from cli.model import ServiceDir
from cli.syft import check_version, run_syft
from core.scan.errors import INVALID_INPUT, SBOM_FAILED
from scan import store
from workflow.common import Deps, scan_id_of, task

SYFT_EXE: Final = "/opt/bin/syft"
SYFT_TIMEOUT_SECONDS: Final = 100.0
SYFT_BASE_ENV: Final[Mapping[str, str]] = {
    "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/bin",
    "HOME": "/tmp",
    "XDG_CACHE_HOME": "/tmp/.cache",
    "XDG_CONFIG_HOME": "/tmp/.config",
}

type RunSyft = Callable[[str, ServiceDir, Sequence[str], float, Mapping[str, str]], dict[str, Any]]
type CheckVersion = Callable[[str, Mapping[str, str]], str]


def load_services(deps: Deps, scan_id: str) -> list[dict[str, Any]]:
    services = json.loads(deps.artefacts.get(store.services_key(scan_id)))
    if not isinstance(services, list):
        raise INVALID_INPUT
    return services


def download_service(
    deps: Deps, scan_id: str, service: Mapping[str, Any], target: Path
) -> ServiceDir:
    """Copy the manifests of ``service`` from S3 into ``target`` and describe the directory."""
    names = []
    for file in service["files"]:
        name = str(file["name"])
        (target / name).write_bytes(
            deps.artefacts.get(store.manifest_key(scan_id, service["index"], name))
        )
        names.append(name)
    return ServiceDir(path=str(service["path"]), directory=target, lockfiles=tuple(sorted(names)))


@task
def run(
    event: dict[str, Any],
    deps: Deps,
    *,
    exe: str = SYFT_EXE,
    syft: RunSyft = run_syft,
    version: CheckVersion = check_version,
) -> dict[str, Any]:
    scan_id = scan_id_of(event)
    index = event.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise INVALID_INPUT
    services = load_services(deps, scan_id)
    if index >= len(services):
        raise INVALID_INPUT
    work = Path(tempfile.mkdtemp(prefix="svc-", dir="/tmp"))
    try:
        service = download_service(deps, scan_id, services[index], work)
        try:
            version(exe, SYFT_BASE_ENV)
            bom = syft(
                exe,
                service,
                [str(s["path"]) for s in services],
                SYFT_TIMEOUT_SECONDS,
                SYFT_BASE_ENV,
            )
        except CliError:
            raise SBOM_FAILED from None  # the CLI message names the service; it is not stored
    finally:
        shutil.rmtree(work, ignore_errors=True)
    key = store.sbom_key(scan_id, index)
    deps.artefacts.put(key, json.dumps(bom).encode())
    return {"index": index, "sbomKey": key}


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    from workflow import runtime

    return run(event, runtime.begin(event))
