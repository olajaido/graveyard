"""Data model and constants for the dependency graph (design §3, §4).

Every dataclass is frozen. Collections are tuples; mappings are read-only
``MappingProxyType`` views built in sorted key order (``scope_map``). This
module does no I/O and imports only ``core.scoring.types.PathInfo``.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

from core.scoring.types import PathInfo

Scope = Literal["runtime", "dev"]
# package_key -> scope; read-only; iteration order sorted by key.
ScopeMap = Mapping[str, Scope]

# --- Constants (structural limits; the BuildGraph handler passes SSM values) ---

SUPPORTED_SPEC_VERSIONS: Final[tuple[str, ...]] = ("1.5", "1.6", "1.7")
DEFAULT_K_PATHS: Final = 3
DEFAULT_MAX_PATH_NODES: Final = 64
DEFAULT_MAX_SERVICES: Final = 50
DEFAULT_MAX_COMPONENTS: Final = 20_000
DEFAULT_MAX_EDGES: Final = 200_000
MAX_LOCKFILE_CHARS: Final = 10_000_000
MAX_WARNINGS_PER_CODE: Final = 50
MAX_SUBJECTS: Final = 20
MAX_TEXT: Final = 200

WARNING_CODES: Final[frozenset[str]] = frozenset(
    {
        "ROOT_NOT_FOUND",
        "MULTIPLE_ROOTS",
        "UNSUPPORTED_PURL",
        "MISSING_PURL",
        "DANGLING_REF",
        "SCOPE_ASSUMED",
        "SCOPE_DISAGREEMENT",
        "DIRECT_UNRESOLVED",
        "LOCKFILE_ENTRY_SKIPPED",
        "REQUIREMENT_SKIPPED",
        "PATHS_OMITTED",
        "WARNINGS_TRUNCATED",
    }
)

_MAX_PATH_INFOS: Final = 4


def path_info_sort_key(info: PathInfo) -> tuple[bool, bool]:
    """Sort key: (runtime, direct), (runtime, transitive), (dev, direct), (dev, transitive)."""
    return (not info.runtime, not info.direct)


def scope_map(items: Mapping[str, Scope]) -> ScopeMap:
    """Return a read-only ``ScopeMap`` whose iteration order is sorted by key."""
    return MappingProxyType({key: items[key] for key in sorted(items)})


@dataclass(frozen=True)
class GraphWarning:
    code: str  # member of WARNING_CODES (DG-WARN-2)
    detail: str  # deterministic, human-readable
    service: str | None = None  # manifest directory, None for graph-level
    subjects: tuple[str, ...] = ()  # sorted keys/refs; at most MAX_SUBJECTS


@dataclass(frozen=True)
class ScopeResult:
    """Returned by every lockfile parser (DG-SCP-0)."""

    package_scopes: ScopeMap  # every package in the lockfile
    direct_scopes: ScopeMap  # the project's declared direct dependencies; may be empty
    warnings: tuple[GraphWarning, ...]  # service is None here; build_graph stamps it


@dataclass(frozen=True)
class ServiceInput:
    path: str  # manifest directory, e.g. "services/api"; unique per call
    bom: Mapping[str, Any]  # parsed CycloneDX JSON
    scopes: ScopeResult | None = None  # from a lockfile parser; None => D8


@dataclass(frozen=True)
class ExamplePath:
    service: str
    nodes: tuple[str, ...]  # package_keys, root excluded (D7)


@dataclass(frozen=True)
class PathWitness:
    path_info: PathInfo  # the member this path realises
    path: ExamplePath


@dataclass(frozen=True)
class GraphNode:
    key: str  # package_key
    purl: str  # canonical purl, qualifiers/subpath dropped, case preserved (DG-DUP-3)
    manifests: tuple[str, ...]  # sorted service paths whose SBOM contains the package
    path_infos: tuple[PathInfo, ...]  # sorted, unique, 0..4 members
    services_affected: int
    example_paths: tuple[ExamplePath, ...]  # up to K shortest (D6)
    path_witnesses: tuple[PathWitness, ...]  # at most one per path_infos member (D13)

    def __post_init__(self) -> None:
        """Validate DG-OUT-3. O(1) per node: nothing is recomputed."""
        infos = self.path_infos
        if len(infos) > _MAX_PATH_INFOS:
            raise ValueError(f"{self.key}: path_infos has {len(infos)} members, at most 4 allowed")
        if len(set(infos)) != len(infos):
            raise ValueError(f"{self.key}: path_infos members must be unique")
        if list(infos) != sorted(infos, key=path_info_sort_key):
            raise ValueError(f"{self.key}: path_infos must be sorted (DG-EXP-5)")
        if self.services_affected < 0:
            raise ValueError(f"{self.key}: services_affected must be >= 0")
        if (self.services_affected == 0) != (len(infos) == 0):
            raise ValueError(f"{self.key}: services_affected is 0 iff path_infos is empty")
        witnessed = [w.path_info for w in self.path_witnesses]
        if len(set(witnessed)) != len(witnessed):
            raise ValueError(f"{self.key}: path_witnesses must be unique per path_infos member")
        if not set(witnessed) <= set(infos):
            raise ValueError(f"{self.key}: path_witnesses must be drawn from path_infos")

    @property
    def direct(self) -> bool:
        return any(p.direct for p in self.path_infos)

    @property
    def transitive(self) -> bool:
        return any(not p.direct for p in self.path_infos)

    @property
    def scope(self) -> Scope | None:
        if not self.path_infos:
            return None
        return "runtime" if any(p.runtime for p in self.path_infos) else "dev"


@dataclass(frozen=True)
class DependencyGraph:
    services: tuple[str, ...]  # sorted
    nodes: tuple[GraphNode, ...]  # sorted by key; lookup via .node(key)
    warnings: tuple[GraphWarning, ...]  # sorted, de-duplicated, capped

    def node(self, key: str) -> GraphNode | None:
        """Return the node with ``key`` or ``None``, in O(log n)."""
        i = bisect_left(self.nodes, key, key=lambda n: n.key)
        if i < len(self.nodes) and self.nodes[i].key == key:
            return self.nodes[i]
        return None
