"""From a GitHub tree to the services of a scan (SB-FET-3, SB-FET-4). Pure."""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from cli.discover import SKIP_DIRS, is_lockfile_name
from core.scan.errors import NO_MANIFESTS, TOO_LARGE

_REGULAR_FILE_MODE: Final = {"100644", "100755"}


@dataclass(frozen=True)
class Limits:
    max_services: int
    max_manifest_bytes: int
    max_file_bytes: int


@dataclass(frozen=True)
class ManifestFile:
    name: str
    path: str  # path in the repository
    sha: str  # blob SHA
    size: int


@dataclass(frozen=True)
class ServicePlan:
    path: str  # directory; "." is the repository root
    files: tuple[ManifestFile, ...]


def ecosystem_of(name: str) -> str:
    """``npm`` or ``pypi`` for a supported lockfile name (``is_lockfile_name`` is true for it)."""
    return "npm" if name == "package-lock.json" else "pypi"


def describe_services(plans: Iterable[ServicePlan]) -> list[dict[str, Any]]:
    """The ``services`` of a scan (ui-core B3): one entry per service, no duplicate ``id``.

    ``id`` is the directory (``.`` for the root) and equals the service names the graves carry. The
    lockfiles of a service are in name order.
    """
    return [
        {
            "id": plan.path,
            "manifests": [
                {"ecosystem": ecosystem_of(f.name), "path": f.path}
                for f in sorted(plan.files, key=lambda f: f.name)
            ],
        }
        for plan in sorted(plans, key=lambda plan: plan.path)
    ]


def _skipped(path: str) -> bool:
    return any(part in SKIP_DIRS for part in path.split("/")[:-1])


def select_services(entries: Iterable[Mapping[str, Any]], limits: Limits) -> list[ServicePlan]:
    """Group the supported lockfiles of ``entries`` by directory, sorted by directory path.

    Raises ``NO_MANIFESTS`` when there is none and ``TOO_LARGE`` when a limit is exceeded.
    """
    by_dir: dict[str, list[ManifestFile]] = {}
    total = 0
    for entry in entries:
        path = entry.get("path")
        if (
            entry.get("type") != "blob"
            or entry.get("mode") not in _REGULAR_FILE_MODE
            or not isinstance(path, str)
            or not isinstance(entry.get("sha"), str)
            or not isinstance(entry.get("size"), int)
        ):
            continue
        name = posixpath.basename(path)
        if not is_lockfile_name(name) or _skipped(path):
            continue
        size = entry["size"]
        if size > limits.max_file_bytes:
            raise TOO_LARGE
        total += size
        if total > limits.max_manifest_bytes:
            raise TOO_LARGE
        directory = posixpath.dirname(path) or "."
        by_dir.setdefault(directory, []).append(ManifestFile(name, path, entry["sha"], size))
    if not by_dir:
        raise NO_MANIFESTS
    if len(by_dir) > limits.max_services:
        raise TOO_LARGE
    return [
        ServicePlan(directory, tuple(sorted(files, key=lambda f: f.name)))
        for directory, files in sorted(by_dir.items())
    ]
