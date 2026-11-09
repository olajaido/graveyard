# Spec: dependency-graph

> **Source of truth:** PRD EX-4, EX-6, EX-7, EX-8 and §7.5 (exposure); `docs/adr/0001-data-sources-and-sbom.md` (decisions 1 and 2); `docs/SPIKES.md` (Q5 Syft output shape, Q6 npm purl case); the existing `core.purl` (`parse_purl`, `package_key`) and `core.scoring.types.PathInfo`.
> **Scope:** pure logic in `backend/core/graph/`:
> 1. ingest of CycloneDX 1.5–1.7 JSON (already-parsed `dict`s) for one or more services into one graph keyed by `package_key`;
> 2. pure lockfile-text parsers for scope enrichment (`package-lock.json`, `poetry.lock`, `uv.lock`, `requirements.txt`);
> 3. exposure inputs per node: the reachable `PathInfo` set (≤ 4 members), computed in O(V+E) without path enumeration;
> 4. display paths per node: up to K shortest example paths, plus one witness path per `PathInfo` member; `services_affected`; direct/transitive flags;
> 5. structured warnings for every recoverable anomaly (the module never logs).
>
> **Out of scope:** running Syft or any subprocess (`syft-sbom-lambda`); fetching manifests (`exhume-github`); SPDX input; presigned upload and the 5 MB cap (`exhume-sbom-upload`); CycloneDX *export* and the "ingest → export → ingest" property (`coroners-report`, see D16); exposure weights and the priority formula (`mortality-model`); the `BuildGraph` Step Functions handler (`backend/workflow/`); any network or file I/O.

---

## Design decisions recorded by this spec

| ID | Decision | Rationale and consequence |
|----|----------|---------------------------|
| D1 | **Node identity is `package_key`, never the bom-ref and never the full purl.** A bom-ref is an opaque string. | Syft's `bom-ref` is `purl + "?package-id=<hash>"`, and for npm it is lower-cased while the `purl` keeps the original case (`SPIKES.md` Q6: `purl` `pkg:npm/JSONStream@1.3.5`, `bom-ref` `pkg:npm/jsonstream@1.3.5?package-id=…`). Edges are resolved by exact bom-ref match to a component, then through that component's `purl` field to `package_key`. Nothing parses or strips the suffix, so it cannot matter. |
| D2 | **Edges and reachability are per service; results are unioned.** | Two services may pin the same `package_key` but with different `dependsOn` lists. A merged edge set would let service A's root reach nodes through edges that only service B recorded. Nodes are shared (EX-7); edges are not. |
| D3 | **The service root is not a package.** It is excluded from the node set and has no `package_key` in the output. Edges into the root are ignored. | The root is the project being scanned, not something to autopsy. A cycle back to the root can never be part of a simple path from the root. |
| D4 | **`PathInfo.runtime` of a path is the scope of its first hop (the direct dependency); `PathInfo.direct` is "the path has exactly one node".** | EX-8: "a package reachable via any runtime direct dependency is runtime". The scope of the other nodes on the path is irrelevant to that path. Scope therefore only matters for direct dependencies (see D11). |
| D5 | **Exposure semantics are those of *simple* paths** (no repeated node), but are computed without enumerating them. | The brute-force oracle enumerates simple paths. The implementation must agree with it on cyclic graphs. The trap: a direct dependency `n` on a cycle through itself is **not** made transitive by that cycle alone, because a simple path cannot revisit its own first hop. |
| D6 | **Example paths are the first K *minimum-length* paths** in the total order `(service path, node tuple read from the node backwards)`. | Minimum-length paths live in a shortest-path DAG: acyclic by construction and lazily enumerable in O(K·L). K-shortest-*simple*-paths (Yen) is not linear and adds nothing to a "how does this reach me" display. Reading the tuple backwards (nearest dependency first) lets the order fall out of a backward walk of the DAG with sorted predecessors. If fewer than K minimum-length paths exist, fewer are returned. |
| D7 | **Paths exclude the root.** `path[0]` is a direct dependency of the root of `ExamplePath.service`; `path[-1]` is the node (review decision 1). | The root has no `package_key` (D3) and, in uploaded SBOMs, may have no purl. |
| D8 | **Unknown scope defaults to runtime and is reported.** | When no scope data is supplied, or a direct dependency is not in it, the conservative choice is the higher exposure weight. Missing is never silently treated as dev (mortality-model: missing ≠ healthy). |
| D9 | **Ingest never raises for data it can skip.** It records a warning. It raises `ValueError` only for malformed structure. | A component with an unsupported purl type (e.g. `maven`) or no purl must not fail the scan (AU-4 spirit). A document that is not CycloneDX 1.5–1.7, or whose types are wrong, cannot be interpreted and is rejected. |
| D10 | **No new dependency.** Parsing uses `json`, `tomllib` (stdlib, Python 3.12), `re`, `collections`, `bisect`, and `core.purl`. | `tech.md` pinning rules; PV-DEP-3 precedent. |
| D11 | **Direct-edge scope comes from the lockfile's declaration of the project's own dependencies, falling back to per-package flags.** Precedence: `ScopeResult.direct_scopes` → `ScopeResult.package_scopes` → `runtime` with a warning (D8). (review decision 6) | The scope that matters is "how does the *project* depend on this", which `packages[""]` in `package-lock.json` and the project entry in `uv.lock` state directly. `package.json` is not read. Per-package flags are a cross-check in one direction only: a package declared `runtime` that the lockfile marks dev-only is inconsistent and gets a `SCOPE_DISAGREEMENT` warning (the declaration still wins, which is the conservative choice). The opposite case, declared `dev` while production also requires the package (npm then marks it non-dev), is normal and emits nothing: the node gets `(dev, direct)` for the declaration and `(runtime, transitive)` through the production dependency, which is already the full picture. |
| D12 | **`devOptional` counts as runtime.** (review decision 5) | npm sets `devOptional` on a package reachable from dev dependencies and from *optional* dependencies of non-dev packages, so it can be installed in production. Treating it as dev would under-weight it. Conservative for exposure. |
| D13 | **Every node also carries one *witness* path per `PathInfo` member** (≤ 4), in addition to the K shortest paths. (review decision 2) | So the UI can explain "why runtime" and "why direct" even when the K shortest paths are all of one kind. A witness is a minimum-length simple path among those that realise that `PathInfo`. It is independent of K: `k_paths=0` still returns witnesses. A witness may equal one of the K shortest; the two lists are not de-duplicated against each other. |
| D14 | **`GraphWarning` is the only diagnostics channel.** No logging, printing, or `warnings.warn`. (review decision 4) | The module is pure. Callers (the `BuildGraph` handler) decide what to log. Every recoverable anomaly, including those found by the lockfile parsers, becomes a structured warning in the result. |
| D15 | **Example and witness paths longer than `max_path_nodes` (default 64) are omitted** and one `PATHS_OMITTED` warning records which nodes. `path_infos` and `services_affected` are unaffected. | A 5,000-node chain would otherwise return Σ(1..5000) ≈ 12.5 M path elements. Real dependency depth is far below 64. The cap bounds result size for untrusted input (threat T7). |
| D16 | **The "ingest → export → ingest is a fixed point" property belongs to `coroners-report`**, which owns CycloneDX export. This spec has no exporter and replaces it with determinism and dedupe-idempotence properties. (review decision 3) | `testing.md` and PRD §11.6 are updated to say so. |

---

## Data model

```python
Scope = Literal["runtime", "dev"]
ScopeMap = Mapping[str, Scope]          # package_key -> scope; read-only; iteration order sorted by key

@dataclass(frozen=True)
class GraphWarning:
    code: str                           # member of WARNING_CODES (DG-WARN-2)
    detail: str                         # deterministic, human-readable
    service: str | None = None          # manifest directory, None for graph-level
    subjects: tuple[str, ...] = ()      # sorted package_keys / refs the warning is about; at most MAX_SUBJECTS

@dataclass(frozen=True)
class ScopeResult:                      # returned by every lockfile parser (DG-SCP-0)
    package_scopes: ScopeMap            # every package in the lockfile
    direct_scopes: ScopeMap             # the project's declared direct dependencies; empty when the format does not record them
    warnings: tuple[GraphWarning, ...]  # service is None here; build_graph stamps it

@dataclass(frozen=True)
class ServiceInput:
    path: str                           # manifest directory, e.g. "services/api"; unique per call
    bom: Mapping[str, Any]              # parsed CycloneDX JSON (json.loads already done by the caller)
    scopes: ScopeResult | None = None   # from a lockfile parser; None => D8

@dataclass(frozen=True)
class ExamplePath:
    service: str
    nodes: tuple[str, ...]              # package_keys, root excluded (D7)

@dataclass(frozen=True)
class PathWitness:
    path_info: PathInfo                 # the member this path realises
    path: ExamplePath

@dataclass(frozen=True)
class GraphNode:
    key: str                            # package_key
    purl: str                           # canonical purl, qualifiers/subpath dropped, case preserved (DG-DUP-3)
    manifests: tuple[str, ...]          # sorted service paths whose SBOM contains the package (EX-4)
    path_infos: tuple[PathInfo, ...]    # reachable (runtime, direct) combinations, sorted, 0..4 members
    services_affected: int
    example_paths: tuple[ExamplePath, ...]    # up to K shortest (D6)
    path_witnesses: tuple[PathWitness, ...]   # one per path_infos member (D13)
    # derived properties: direct, transitive, scope

@dataclass(frozen=True)
class DependencyGraph:
    services: tuple[str, ...]           # sorted
    nodes: tuple[GraphNode, ...]        # sorted by key; lookup via .node(key)
    warnings: tuple[GraphWarning, ...]  # sorted, de-duplicated, capped
```

Public functions (re-exported from `core.graph`):

```python
def build_graph(services: Sequence[ServiceInput], *, k_paths: int = 3, max_path_nodes: int = 64,
                max_services: int = 50, max_components: int = 20_000, max_edges: int = 200_000
                ) -> DependencyGraph: ...
def parse_package_lock(text: str) -> ScopeResult: ...
def parse_poetry_lock(text: str) -> ScopeResult: ...
def parse_uv_lock(text: str) -> ScopeResult: ...
def parse_requirements_txt(text: str) -> ScopeResult: ...
def exposure_inputs(node: GraphNode) -> tuple[tuple[PathInfo, ...], int]: ...   # (paths, services_affected) for Signals
def graph_to_dict(graph: DependencyGraph) -> dict[str, Any]: ...                # JSON-compatible, canonical
```

`design.md` fixes the final signatures; the behaviour below is the contract. The numeric defaults are module constants. The `BuildGraph` handler passes the SSM-held values (`tech.md`: no hard-coded runtime config), and the constants are only the fallbacks.

---

## Dependency and purity

| ID | Requirement |
|----|-------------|
| DG-DEP-1 | **THE SYSTEM SHALL NOT** add any runtime or dev dependency for this spec (D10). `uv run mypy --strict core` SHALL pass with no `type: ignore`. |
| DG-DEP-2 | **THE SYSTEM SHALL** import `PathInfo` from `core.scoring.types` and use `parse_purl`, `format_purl`, `package_key` and `Purl` from `core.purl`. It SHALL NOT redefine them, and SHALL NOT hand-format package keys. |
| DG-PURE-1 | `backend/core/graph/` SHALL perform no I/O and emit no diagnostics: no file, network, environment or clock access, no subprocess, no logging, printing or `warnings.warn` (D14). A test SHALL parse every module under `core/graph/` (excluding `tests/`) with `ast` and fail if it imports `os`, `subprocess`, `socket`, `urllib`, `http`, `shutil`, `tempfile`, `logging`, `warnings`, `datetime`, `time`, or `random`, calls `open`, `print` or `input`, or imports from `backend/sources`, `backend/workflow`, `backend/rites` or `core.scoring` other than `core.scoring.types` (`structure.md` separation rules). |
| DG-PURE-2 | Every public function SHALL be deterministic (DG-OUT-1) and SHALL NOT mutate its arguments. A test SHALL deep-copy each input, call the function, and assert the input is unchanged. |
| DG-PURE-3 | Traversal SHALL be iterative. No function SHALL depend on the Python recursion limit (DG-OUT-5). |

---

## Warnings (D14)

| ID | Requirement |
|----|-------------|
| DG-WARN-1 | Every recoverable anomaly, in ingest, scope application and the lockfile parsers, SHALL be reported as a `GraphWarning` and never by logging or printing. A condition is *recoverable* when skipping it cannot make an emitted `PathInfo`, edge or scope wrong; anything else raises `ValueError` (DG-ING-2, 3, 7, 8). |
| DG-WARN-2 | `code` SHALL be one of the closed set `WARNING_CODES`: <br>• `ROOT_NOT_FOUND`: no root entry in a service (DG-ROOT-4). <br>• `MULTIPLE_ROOTS`: several root entries; `subjects` are the root bom-refs, sorted. <br>• `UNSUPPORTED_PURL`: a component whose purl `parse_purl` rejects (including types other than npm and pypi). <br>• `MISSING_PURL`: a `library` or `application` component without a purl. <br>• `DANGLING_REF`: a `ref` or `dependsOn` entry that resolves to no usable component. <br>• `SCOPE_ASSUMED`: direct dependencies with no scope data (D8). <br>• `SCOPE_DISAGREEMENT`: a direct dependency declared `runtime` whose per-package scope is `dev` (D11, DG-SCP-5). It is never raised for a package declared `dev`. <br>• `DIRECT_UNRESOLVED`: a lockfile root dependency with no installed entry (`package-lock.json`, `uv.lock`). <br>• `LOCKFILE_ENTRY_SKIPPED`: a lockfile entry whose name or version cannot form a valid purl. <br>• `REQUIREMENT_SKIPPED`: an unpinned, ranged, URL or path line in `requirements.txt`. <br>• `PATHS_OMITTED`: example or witness paths dropped by `max_path_nodes` (D15). <br>• `WARNINGS_TRUNCATED`: warnings dropped by the cap (DG-WARN-4). |
| DG-WARN-3 | `build_graph` SHALL include every warning from each `ServiceInput.scopes.warnings`, stamped with that service's `path`. Parser warnings carry `service=None`. |
| DG-WARN-4 | The final warning list SHALL be sorted by `(service or "", code, detail, subjects)`, de-duplicated, and capped at `MAX_WARNINGS_PER_CODE` (50) per `(service, code)`. When a group is truncated, one `WARNINGS_TRUNCATED` warning for that group SHALL state the code and the number omitted. `subjects` SHALL be sorted, de-duplicated and capped at `MAX_SUBJECTS` (20), with the total stated in `detail`. Each subject and each `detail` SHALL be truncated to `MAX_TEXT` (200) characters. The parsers apply the same cap to their own warnings. |
| DG-WARN-5 | Warning text SHALL be built only from input values (truncated) and fixed strings. It SHALL NOT contain memory addresses, timestamps, exception reprs of unrelated objects, or absolute paths. |

---

## Ingest: CycloneDX 1.5–1.7 (EX-4, EX-6, EX-7)

| ID | Requirement |
|----|-------------|
| DG-ING-1 | **THE SYSTEM SHALL** provide `build_graph(services)`, which turns one or more `ServiceInput`s into one `DependencyGraph`. Each `ServiceInput.path` is one *service* (EX-6): a manifest directory. |
| DG-ING-2 | **IF** a BOM is not a mapping, has `bomFormat` present and not `"CycloneDX"`, has a missing or non-string `specVersion`, or has a `specVersion` other than `"1.5"`, `"1.6"` or `"1.7"` **THEN** `build_graph` SHALL raise `ValueError` naming the service path and the offending field. Pinned Syft 1.56.0 emits `"1.7"`. |
| DG-ING-3 | **IF** `components` or `dependencies` is present and has the wrong type (not a list; an element not a mapping; `ref` or `bom-ref` not a non-empty string; `dependsOn` present and not a list of strings; `purl` present and not a string; `type` present and not a string) **THEN** `build_graph` SHALL raise `ValueError` naming the service path and the field. Absent `components`, `dependencies` or `dependsOn` SHALL be treated as empty. Unknown fields SHALL be ignored. |
| DG-ING-4 | **THE SYSTEM SHALL** flatten nested `components` (CycloneDX allows components inside components; cdxgen emits them) using an explicit stack, so every component is visible at any depth. |
| DG-ING-5 | **THE SYSTEM SHALL** map each component to a node as follows: take its `purl`; `parse_purl` it; take `package_key`. A component with no `purl` SHALL be skipped with a `MISSING_PURL` warning only when its `type` is `library` or `application`; other types (Syft's `file` entry for the lockfile) are skipped silently. A component whose purl `parse_purl` rejects SHALL be skipped with an `UNSUPPORTED_PURL` warning; its `detail` names the purl type or the `ValueError` message, truncated (DG-WARN-4). |
| DG-ING-6 | **THE SYSTEM SHALL** resolve each `dependencies[].ref` and each `dependsOn` entry by **exact string match** to a component `bom-ref` (D1). It SHALL NOT parse, strip or compare the `?package-id=` suffix. A `dependsOn` entry that matches no component, or matches a skipped component, SHALL be dropped with a `DANGLING_REF` warning. |
| DG-ING-7 | **IF** two components in one BOM share a `bom-ref` but map to different `package_key`s (or one of them is skipped and the other is not) **THEN** `build_graph` SHALL raise `ValueError`: the BOM breaks the CycloneDX uniqueness rule and its edges are ambiguous. Two components with the same `bom-ref` and the same `package_key` are a harmless duplicate (DG-DUP-1). |
| DG-ING-8 | **THE SYSTEM SHALL** raise `ValueError` for: more than `max_services` services (default 50, the PRD §10 manifest cap); a duplicate, empty or non-string `ServiceInput.path`; a BOM with more than `max_components` components after flattening (default 20,000); a BOM with more than `max_edges` distinct non-root edges (default 200,000). The count is of distinct `(source key, target key)` pairs between packages, after self-edges are dropped (DG-ING-10), so several bom-refs or several entries that map to the same pair count once. Edges from a root to its direct dependencies are not counted: a root edge ends at a distinct direct dependency, so the number of root edges is bounded by `max_components`. The limits are keyword arguments, not literals in the algorithm. |
| DG-ING-9 | **THE SYSTEM SHALL** accept an empty `services` sequence and return an empty graph. A service whose BOM has no packages yields no nodes and no error. |
| DG-ING-10 | Self-edges (`A` depends on `A`) and edges whose target is a service root SHALL be ignored. Neither can be part of a simple path from the root. |

### Root identification (EX-S1, ADR 0001 decision 1)

| ID | Requirement |
|----|-------------|
| DG-ROOT-1 | **THE SYSTEM SHALL** treat a `dependencies` entry as a **root entry** when its `ref` is not listed in any `dependsOn` in the same BOM, **and** either (a) its `ref` equals `metadata.component.bom-ref`, or (b) its `ref` is the `bom-ref` of a component in `components` and its `dependsOn` is non-empty. An unreferenced entry with an empty `dependsOn` that is not the metadata root is an orphan: it stays a node and raises no warning. |
| DG-ROOT-2 | **THE SYSTEM SHALL NOT** rely on `metadata.component` to find the root. In Syft output `metadata.component.bom-ref` is a directory hash that appears neither in `components` nor in `dependencies` (recorded fixtures: `d77b2f1eba698105` for py, `6fb2060e44576377` for npm), so clause (b) finds the project component through `components` (`pkg:pypi/graveyard-spike-py-fixture@0.0.1?package-id=a09d45df5864ec74`; `pkg:npm/graveyard-spike-npm-fixture@0.0.1?package-id=3491eba9e54c1ca3`). Clause (a) exists only so spec-conformant uploaded SBOMs (cdxgen and others), whose root is described in `metadata` and absent from `components`, also work. |
| DG-ROOT-3 | **THE SYSTEM SHALL** exclude each root entry's own component (when present in `components`) from the node set (D3). The root's `dependsOn` targets are the service's **direct dependencies**. |
| DG-ROOT-4 | **IF** exactly one root entry is found **THEN** it is the root. **IF** more than one is found **THEN** all are roots of that service, the union of their children is the direct set, and a `MULTIPLE_ROOTS` warning SHALL be recorded (review decision 4). **IF** none is found **THEN** the service contributes its packages as nodes with no paths, and a `ROOT_NOT_FOUND` warning SHALL be recorded. Neither case raises. |
| DG-ROOT-5 | The root-selection rule SHALL be independent of the order of `components`, `dependencies` and `dependsOn`. |

### Dedupe (EX-7)

| ID | Requirement |
|----|-------------|
| DG-DUP-1 | **THE SYSTEM SHALL** merge all components that map to the same `package_key`, **within** a service (different `?package-id=` hashes, different npm case such as `JSONStream` vs `jsonstream`, different qualifiers) and **across** services, into one node. Within a service, the edges of all merged bom-refs are unioned. |
| DG-DUP-2 | The merge SHALL be idempotent: duplicating any component, any `dependencies` entry or any `dependsOn` element in a BOM SHALL NOT change the output. |
| DG-DUP-3 | `GraphNode.purl` SHALL be the lexicographically smallest `format_purl(...)` string, with qualifiers and subpath dropped, among the merged components. Case is preserved (`pkg:npm/JSONStream@1.3.5`, not `…jsonstream…`), so `registry_name` stays usable for registry calls. The choice SHALL NOT depend on input order. |
| DG-DUP-4 | `GraphNode.manifests` SHALL list every service whose BOM contains the package (EX-4), sorted, even if the root does not reach it there. |
| DG-DUP-5 | Different versions of the same package are different `package_key`s and therefore different nodes (EX-7 is `purl@version`). |

---

## Scope enrichment (EX-8)

All four parsers take **text** and return a `ScopeResult` (D11). They are pure; the caller reads the file. Keys are built with `core.purl`, so they equal the keys `build_graph` produces. Return maps are read-only and iterate in sorted key order.

| ID | Requirement |
|----|-------------|
| DG-SCP-0 | **Common contract.** For any `str` input a parser SHALL return a `ScopeResult` or raise `ValueError`, and nothing else. Text longer than `MAX_LOCKFILE_CHARS` (10,000,000, the PRD §10 manifest budget) SHALL raise `ValueError` before parsing. A `RecursionError` raised by the JSON or TOML decoder on deeply nested input SHALL be converted to `ValueError`. An entry whose name or version cannot form a valid purl SHALL be skipped with a `LOCKFILE_ENTRY_SKIPPED` warning. Parsing SHALL NOT take more than linear time in the input size (no regex with catastrophic backtracking). |
| DG-SCP-1 | **`parse_package_lock(text)`: per-package scope.** Parse JSON and read `packages` (lockfile v2 and v3, EX-2). **IF** `packages` is absent (lockfile v1) **THEN** raise `ValueError` stating that v1 is unsupported. For each entry with a non-empty path key containing `node_modules/` and a string `version`: the package is `dev` when `dev` is true; otherwise `runtime`. In particular `devOptional`, `optional` and `peer` do **not** make a package `dev` (D12). Entries with `link: true`, the root entry `""`, and entries whose path has no `node_modules/` segment (workspace member sources) are skipped without a warning. |
| DG-SCP-2 | The npm package name SHALL be taken from the entry's `name` field when it is a non-empty string (npm aliases), otherwise from the segment after the **last** `node_modules/` in the path key (so `node_modules/a/node_modules/@s/b` yields `@s/b`). |
| DG-SCP-3 | **WHEN** several lockfile entries yield the same `package_key` (nested copies) **THE SYSTEM SHALL** report `runtime` if **any** of them is runtime. |
| DG-SCP-4 | **`parse_package_lock`: declared direct scope (D11).** Read the root entry `packages[""]`. A name in `dependencies`, `optionalDependencies` or `peerDependencies` is declared `runtime`; a name only in `devDependencies` is declared `dev`. For each declared name, find the entry at `node_modules/<name>` and build the key from its `name` (if any) and `version`. The result goes in `direct_scopes`. A declared name with no such entry, or whose entry is a `link`, SHALL be skipped with a `DIRECT_UNRESOLVED` warning. **IF** `packages[""]` is absent **THEN** `direct_scopes` is empty and no warning is raised. `package.json` is never read. |
| DG-SCP-5 | **Cross-check (one direction only).** For each resolved declared dependency that is declared `runtime` while its `package_scopes` entry is `dev`, the parser SHALL emit one `SCOPE_DISAGREEMENT` warning with the key as the only subject and both scopes in `detail`. The lockfile is inconsistent: the project declares a production dependency that the lockfile marks dev-only. `direct_scopes` keeps `runtime` (the declaration wins, D11) and `package_scopes` keeps `dev`. A package declared `dev` whose per-package scope is `runtime` (a devDependency that production also requires) is **not** a disagreement and SHALL emit nothing. The check is one shared helper in `scopes_common.py`, applied by every parser that fills both maps; for `parse_uv_lock` it cannot fire, because both maps come from the same seeds (DG-SCP-7). |
| DG-SCP-6 | **`parse_poetry_lock(text)`.** Parse TOML with `tomllib`; read each `[[package]]`. A package is `runtime` when its `groups` list contains `"main"` (Poetry ≥ 2.0), or, when `groups` is absent, when `category == "main"` (Poetry < 2.0); otherwise `dev`. A package with neither field is `runtime` (D8). `direct_scopes` is empty: `poetry.lock` does not record the project's own dependencies, and `pyproject.toml` is not read. |
| DG-SCP-7 | **`parse_uv_lock(text)`.** Parse TOML. *Project packages* are `[[package]]` entries whose `source` table has a `virtual` or `editable` key; they are not in the result. Dependency references `{name, version?}` resolve to every package with the PEP 503-normalised name, narrowed to a matching `version` when one is given. <br>• `direct_scopes`: targets of a project package's `dependencies` and `optional-dependencies` are `runtime`; targets of `dev-dependencies` (all groups) are `dev`; a target in both is `runtime`. A reference that resolves to nothing SHALL be skipped with a `DIRECT_UNRESOLVED` warning. <br>• `package_scopes`: following each package's `dependencies` and all `optional-dependencies` (an iterative closure that tolerates cycles), a package reachable from any runtime seed is `runtime`; one reachable only from dev seeds is `dev`; one reachable from no seed is `runtime` (D8). A package declared `runtime` is always in the runtime closure, so DG-SCP-5 never fires for `uv.lock`. |
| DG-SCP-8 | **`parse_requirements_txt(text)`.** Every **pinned** requirement is `runtime` in both `package_scopes` and `direct_scopes`. A line is pinned when it is `name==version` or `name===version` with a plain version (no `*`), optionally with extras (`name[extra]==1.0`), spaces around the operator, an environment marker (`; python_version < "3.9"`), `--hash=…` options (including `\` line continuations) and a trailing comment. Blank lines, comment lines and option lines (`-r`, `-c`, `-e`, `--index-url`, …) SHALL be skipped silently. Unpinned or ranged specifiers (`>=`, `~=`, `==1.*`) and URL or path requirements SHALL be skipped with a `REQUIREMENT_SKIPPED` warning. A leading UTF-8 BOM and `\r\n` line endings SHALL be accepted. It SHALL NOT raise for any text. |
| DG-SCP-9 | **Applying scopes in `build_graph`.** For each direct dependency `d` of a service root, its scope is `direct_scopes[d]` if present, else `package_scopes[d]` if present, else `runtime`. For every `d` falling through to the last case, and when `scopes` is `None`, **one** `SCOPE_ASSUMED` warning per service SHALL be recorded, with the affected keys as `subjects`. Scopes of non-direct nodes never affect any `PathInfo` (D4). |

---

## Exposure inputs (§7.5, no path enumeration)

| ID | Requirement |
|----|-------------|
| DG-EXP-1 | **THE SYSTEM SHALL** compute, for every node, `path_infos`: the set of `PathInfo(runtime, direct)` for which **at least one simple path** from the root of at least one service to the node exists, where `runtime` is the scope of the path's first hop and `direct` is "the path has exactly one node" (D4, D5). The result has at most four members. |
| DG-EXP-2 | **THE SYSTEM SHALL** compute `path_infos` in time O(V+E) per service (O(Σ(V_s+E_s)) overall) by graph traversal, without enumerating paths. A test SHALL complete a 40-layer, 2-wide diamond graph (about 2^40 paths) within the NFR time budget. |
| DG-EXP-3 | **THE SYSTEM SHALL** be cycle-safe: for any graph, including cycles, self-loops and cycles through direct dependencies, it terminates and returns the simple-path semantics of DG-EXP-1. A direct dependency `n` that lies on a cycle and is reached only from itself has `path_infos == {PathInfo(scope(n), direct=True)}` and **no** transitive member (D5). If another direct dependency of the same scope reaches `n`, the transitive member of that scope is present. |
| DG-EXP-4 | **THE SYSTEM SHALL** give a node that no service root reaches (an orphan component, or a service with `ROOT_NOT_FOUND`) an empty `path_infos`, `services_affected == 0`, and empty `example_paths` and `path_witnesses`. It SHALL NOT invent a default path; the exposure default of 1.0 with `exposure_assumed = True` is the scoring layer's decision (§7.5). |
| DG-EXP-5 | `path_infos` SHALL be sorted as `(runtime, direct)`, `(runtime, transitive)`, `(dev, direct)`, `(dev, transitive)`; members are unique. |
| DG-EXP-6 | `GraphNode` SHALL expose read-only derived properties computed from `path_infos`: `direct` (`any(p.direct)`), `transitive` (`any(not p.direct)`), and `scope` (`"runtime"` if any `p.runtime`; `"dev"` if `path_infos` is non-empty and none is runtime; `None` if empty). A node can be both `direct` and `transitive`. |
| DG-EXP-7 | `exposure_inputs(node)` SHALL return `(node.path_infos, node.services_affected)`, the exact values for `Signals.paths` and `Signals.services_affected`, with `paths` an empty tuple (not `None`) for an unreachable node. It SHALL NOT compute exposure or priority; the weights live in `weights.v1.yaml` (mortality-model). |

### Services affected (EX-6)

| ID | Requirement |
|----|-------------|
| DG-SVC-1 | `services_affected` SHALL be the number of distinct services in which the node has a non-empty single-service `path_infos` (DG-EXP-1 applied to that service alone). A node present in a service's SBOM but unreachable there does not count, but is listed in `manifests` (DG-DUP-4). |
| DG-SVC-2 | `services_affected` SHALL be ≤ `len(graph.services)`, ≥ 1 for every node with a non-empty `path_infos`, and 0 for every node with an empty one. |

### Example paths and witnesses (display only)

| ID | Requirement |
|----|-------------|
| DG-PATH-1 | **THE SYSTEM SHALL** return, per node, at most `k_paths` `ExamplePath`s in `example_paths` (default 3). `k_paths` SHALL be an `int ≥ 0` (a `bool` is rejected); `0` returns none; anything else raises `ValueError`. |
| DG-PATH-2 | Every `ExamplePath` and every witness path SHALL: start at a direct dependency of a root of its `service`; end at the node; follow only edges present in that service's merged edge set (DG-DUP-1, DG-ING-10); contain no repeated `package_key`. |
| DG-PATH-3 | Every path in `example_paths` SHALL have the minimum length over all paths to the node in all services. The returned list is the first `k_paths` of the minimum-length paths in the order `(service path, nodes read from the node backwards)` (D6), sorted by that order, with no duplicates. |
| DG-PATH-4 | Path selection SHALL cost O(V+E) per service for the distance pass plus O(K·L) per node for extraction (`L` is the path length), using a shortest-path DAG. |
| DG-PATH-5 | **WHEN** a node has no path **THE SYSTEM SHALL** return empty `example_paths`. |
| DG-PATH-6 | A path with more than `max_path_nodes` nodes SHALL NOT be returned in `example_paths` or `path_witnesses`. When any is omitted, one graph-level `PATHS_OMITTED` warning SHALL list the affected node keys (capped, DG-WARN-4) and state the number of omitted paths (D15). `max_path_nodes` is a keyword argument, an `int ≥ 1`. |
| DG-WIT-1 | **THE SYSTEM SHALL** return in `path_witnesses`, for every member `pi` of `path_infos`, exactly one `PathWitness(pi, path)`, sorted in the same order as `path_infos` (DG-EXP-5), independent of `k_paths`. The only exception is a witness omitted under DG-PATH-6. |
| DG-WIT-2 | The path of `PathWitness(pi, path)` SHALL satisfy DG-PATH-2, and `PathInfo(runtime=(scope_s(path.nodes[0]) == "runtime"), direct=(len(path.nodes) == 1))`, computed in `path.service`, SHALL equal `pi`. |
| DG-WIT-3 | The witness for `pi` SHALL have the minimum length among all simple paths, in all services, whose `PathInfo` is `pi`. Ties are broken by service order, then by the traversal's deterministic choice (design §5.4), which is a function of the graph only and never of input order. A `(scope, direct)` witness is the one-node path `(node,)` in the first service, in sorted order, where the node is a direct dependency of that scope. |
| DG-WIT-4 | `path_witnesses` and `example_paths` are independent lists. A witness MAY equal a member of `example_paths` and SHALL NOT be removed from either for that reason. |

---

## Output and determinism

| ID | Requirement |
|----|-------------|
| DG-OUT-1 | `build_graph` SHALL be a pure function of its inputs: identical inputs give equal outputs. The result SHALL NOT depend on the order of `services`, `components`, nested components, `dependencies`, `dependsOn`, or the key order of any mapping, including the maps in `ScopeResult`. |
| DG-OUT-2 | All collections in the output SHALL be immutable and sorted: tuples in their documented order, `nodes` sorted by key. All dataclasses SHALL be `frozen=True`. `graph_to_dict(graph)` SHALL return a JSON-compatible `dict` with a canonical key order, so `json.dumps(graph_to_dict(g), sort_keys=False)` is byte-stable. `DependencyGraph.node(key)` SHALL return the node or `None` in O(log n). |
| DG-OUT-3 | `GraphNode` SHALL validate its own invariants in `__post_init__` and raise `ValueError` otherwise: `path_infos` unique and sorted, ≤ 4; `services_affected ≥ 0` and `0` iff `path_infos` is empty; `path_witnesses` members drawn from `path_infos`, unique per member. |
| DG-OUT-4 | `build_graph` SHALL raise only `ValueError` for any input. The parsers SHALL raise only `ValueError`. |
| DG-OUT-5 | **No dependence on the recursion limit.** A 5,000-node chain, a 5,000-node ring and a 5,000-node star (one service each) SHALL be handled within the NFR time budget, with correct `path_infos`, without `RecursionError`. For the chain, paths deeper than `max_path_nodes` are omitted with a `PATHS_OMITTED` warning (D15). |

---

## Non-functional

| ID | Requirement |
|----|-------------|
| DG-NFR-1 | **Performance.** `build_graph` for one service of 1,000 packages and about 2,000 edges (the PRD scan target) SHALL complete in ≤ 0.5 s on the CI runner; for 50 services of 200 packages each, ≤ 3 s; the 5,000-node shapes of DG-OUT-5, ≤ 2 s each. A complete digraph on 200 nodes (one root, all direct) SHALL complete in ≤ 1 s. Regression tests assert these with a ×4 margin to avoid flakes. |
| DG-NFR-2 | **Coverage.** `core/graph` line coverage ≥ 85% (`testing.md` gate). |
| DG-NFR-3 | **Tests live in `backend/core/graph/tests/`**, fixtures in `backend/core/graph/tests/fixtures/`, resolved via `Path(__file__).parent`, never the working directory (`structure.md` precedent for scoring). Shared Hypothesis strategies live in `tests/strategies.py`; the independent oracle lives in `tests/oracle.py` and imports nothing from `core.graph`. |
| DG-NFR-4 | **Every implementation task in `tasks.md` carries its own example tests and property tests as sub-tasks**, as in `purl-and-versions`. No "write tests at the end" task. |
| DG-NFR-5 | **Commands.** Tests run from `backend/`: `uv run pytest -q core/graph`, `HYPOTHESIS_PROFILE=ci uv run pytest -m property -q core/graph`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy --strict core`. |
| DG-NFR-6 | **Fixtures contain no local paths.** `metadata.component.name` in the recorded Syft BOMs is an absolute path on the author's machine (`/Users/…/spikes/fixtures/npm`). The re-recorded `spikes/npm-sbom.cdx.json` and both copies under `tests/fixtures/` SHALL replace it with a neutral value (`"fixtures/npm"`, `"fixtures/py"`), and nothing else in the BOM SHALL be edited. A test asserts that no fixture contains `/Users/`, `/home/` or a drive-letter path. |
| DG-NFR-7 | **Hypothesis deadlines are explicit.** Tests that run the brute-force oracle set `deadline=timedelta(seconds=5)`. No test sets `deadline=None`. |

---

## Fixtures

| Fixture | Source | Notes |
|---------|--------|-------|
| `syft_npm.cdx.json` | **re-recorded** with `~/.local/bin/syft` 1.56.0 on the current `spikes/fixtures/npm` (lockfile with `JSONStream`), scrubbed (DG-NFR-6); also written back to `spikes/npm-sbom.cdx.json` | The earlier spike BOM (superseded by this re-recording) predated `JSONStream`: 114 components against 116 lockfile entries, 3 root children, no `JSONStream` component. The task stops and asks if Syft 1.56.0 is not at `~/.local/bin/syft` and never substitutes another version. Counts of the new BOM (components, dependency entries, root children, distinct edges) are measured once and pinned in the tests. The expected root children are `express`, `JSONStream`, `moment`, `request` (the four dependencies of `packages[""]`). |
| `syft_py.cdx.json` | copy of `spikes/py-sbom.cdx.json`, scrubbed | 9 components = 7 packages + project + `/uv.lock` file; 2 dependency entries; root children `nose`, `requests`, `six`; `requests` → `certifi`, `charset-normalizer`, `idna`, `urllib3`. |
| `lock_npm.json`, `lock_uv.toml` | copies of `spikes/fixtures/npm/package-lock.json` and `spikes/fixtures/py/uv.lock` | Real, but contain **no** `dev` / `devOptional` / `dev-dependencies` entries (checked). They prove "everything runtime", key parity with Syft, and declared-scope parity. |
| `lock_uv_backend.toml` | frozen copy of the real `backend/uv.lock` (21 `[[package]]` tables: the `graveyard-backend` project package with 2 runtime dependencies and a 6-package `dev` group, and 20 other packages) | Real `uv lock` output with a real dev dependency group. Provenance in the README records the source commit and a SHA-256. It is a snapshot: later changes to `backend/uv.lock` do not alter the fixture. The test recomputes every expected figure from the file itself. |
| `lock_poetry.toml` | **generated by the real tool** in a scratch directory outside the repo: `uvx --from poetry==<latest> poetry lock` (no install) for a tiny `pyproject.toml` with one main and one dev dependency | `<latest>` is the newest Poetry release on PyPI at execution time. The README records the exact version, the command, the generated `pyproject.toml` and the date. If the command fails the task stops and asks. The test asserts whatever scope markers the tool actually wrote (`groups`, `category`, or other), not a guess. |
| `lock_npm_dev.json` | **generated by the real tool** in a scratch directory outside the repo: `npm install --package-lock-only --ignore-scripts` for a tiny `package.json` with `dependencies: {"left-pad": "1.3.0"}`, `devDependencies: {"is-number": "7.0.0"}` and `optionalDependencies: {"uuid": "3.4.0"}` | Nothing is installed or executed. The README records the npm and Node versions, the command, the `package.json` and the date. If the command fails the task stops and asks. The test asserts the flags npm actually wrote (`dev`, `optional`) and the root entry's three dependency groups, not a guess. |
| `lock_npm_edge.json`, `lock_uv_edge.toml`, `lock_poetry_edge.toml`, `requirements.txt` | **hand-written, labelled synthetic** in `fixtures/README.md` | Only for cases a real tool cannot produce from a small project: npm `devOptional`, aliases, workspace `link` entries, nested duplicate copies, a devDependency that production also requires, a runtime declaration flagged `dev`, a name declared in both `dependencies` and `devDependencies`; uv optional-dependencies targets, dev cycles, two versions of one name, a dangling reference; Poetry legacy `category` shape, multi-group `groups` lists, and entries with neither field. Keep each ≤ 15 packages, based on real package names and versions. The v1-lockfile rejection test builds its input inline. |
| `fixtures/README.md` | hand-written | Provenance of every fixture: command, tool version, date, and whether it is recorded or synthetic. |

---

## Example-based tests (pytest, non-property)

| ID | Test |
|----|------|
| DG-EX-1 | **Syft py fixture.** `build_graph([ServiceInput("py", syft_py)])` has exactly 7 nodes: `pypi/nose@1.3.7`, `pypi/requests@2.34.2`, `pypi/six@1.17.0`, `pypi/certifi@2026.10.23`, `pypi/charset-normalizer@3.5.2`, `pypi/idna@3.20`, `pypi/urllib3@2.8.0`. The project component and the `/uv.lock` file component are not nodes. With no scopes: `nose`, `requests`, `six` have `path_infos == (PathInfo(True, True),)`; the other four have `(PathInfo(True, False),)`; every node has `services_affected == 1`; `urllib3`'s only example path is `("pypi/requests@2.34.2", "pypi/urllib3@2.8.0")` and its witness for `(runtime, transitive)` is the same path. One `SCOPE_ASSUMED` warning listing the three direct dependencies; no `ROOT_NOT_FOUND`. |
| DG-EX-2 | **Syft npm fixture (re-recorded).** Node count, direct count and edge count equal the figures measured at recording (pinned constants, each also recomputed in the test from the BOM by independent code). All nodes are reachable; `express`, `JSONStream`, `moment`, `request` are direct; no `ROOT_NOT_FOUND` although `metadata.component.bom-ref` is in neither `components` nor `dependencies` (DG-ROOT-2). Removing or nulling `metadata.component` changes nothing. |
| DG-EX-3 | **Order independence on real data.** Reversing and shuffling (fixed seed) `components`, `dependencies` and every `dependsOn` in both Syft fixtures gives an equal `DependencyGraph`. |
| DG-EX-4 | **bom-ref suffix.** For every npm and pypi component in both fixtures, the node key equals `package_key(parse_purl(component["purl"]))`; no key contains `package-id`; every bom-ref of the form `<purl>?package-id=<hash>` resolves although `<purl>` alone is not a bom-ref. |
| DG-EX-5 | **Case fold (SPIKES Q6).** In `syft_npm.cdx.json` the `JSONStream@1.3.5` component has `purl` `pkg:npm/JSONStream@1.3.5` and a lower-case `bom-ref`; the node key is `npm/jsonstream@1.3.5` and `GraphNode.purl` is `pkg:npm/JSONStream@1.3.5`. A copy with a second component spelled `pkg:npm/jsonstream@1.3.5` under a different bom-ref still yields one node, with the union of both components' edges. |
| DG-EX-6 | **Two services, one shared package (EX-6, EX-7).** Services `services/api` (the py fixture) and `services/worker` (a hand-built BOM whose root depends on `requests@2.34.2` and `idna@3.20`): `requests` and `idna` have `services_affected == 2` and `manifests == ("services/api", "services/worker")`; `nose` has 1; the graph has exactly 7 nodes. Swapping the service order changes nothing. |
| DG-EX-7 | **Per-service edges (D2).** Service A: root → `x`, `x` → `y`. Service B: root → `z`, `z` → `x`, and `x` has no edges. Merged edges would let B reach `y`; the test asserts `services_affected(y) == 1` and that `y`'s only example path has `service == "A"`. |
| DG-EX-8 | **Scope reaches paths (D4, D11).** Direct scopes: `d` dev, `r` runtime; edges `r → t`, `d → t`. `t` has `path_infos == (PathInfo(True, False), PathInfo(False, False))`; `d` has `(PathInfo(False, True),)`; `r` has `(PathInfo(True, True),)`. A dev direct dependency that is also a transitive dependency of a runtime direct dependency has `(PathInfo(True, False), PathInfo(False, True))`. |
| DG-EX-9 | **Cycles.** (a) `root → a → b → a`: `a` is `{(rt, direct)}` only; `b` is `{(rt, transitive)}`. (b) `root → a`, `root → b`, `a ↔ b` (both runtime): `a` and `b` are each `{(rt, direct), (rt, transitive)}`. (c) `root → a` (runtime), `root → b` (dev), `b → a`: `a` is `{(rt, direct), (dev, transitive)}`. (d) a self-loop on a direct dependency changes nothing. (e) the DG-EXP-3 trap with a longer cycle `a → b → c → a`. |
| DG-EX-10 | **Unreachable.** A component present in `components` with no inbound path from the root has empty `path_infos`, `services_affected == 0`, empty `example_paths` and `path_witnesses`, and is still listed under `manifests`. |
| DG-EX-11 | **Warnings.** A BOM with a `pkg:maven/…` component, a `library` component with no `purl`, and a `dependsOn` entry pointing at a missing bom-ref yields `UNSUPPORTED_PURL`, `MISSING_PURL` and `DANGLING_REF` warnings respectively, and still builds the rest of the graph. A `type: file` component with no purl yields no warning. |
| DG-EX-12 | **Rejections.** `specVersion` `"1.4"`, `"2.0"`, missing, and `1.7` (a number rather than a string) raise `ValueError`; `bomFormat: "SPDX"` raises; duplicate service path raises; 51 services raise; conflicting duplicate bom-ref raises; `dependsOn: "x"` raises; a top-level list instead of a mapping raises; `max_components` and `max_edges` exceeded raise. |
| DG-EX-13 | **Spec-conformant upload.** A BOM whose root is `metadata.component` (bom-ref `root`, not in `components`) with a `dependencies` entry for `root` yields the same node set and `path_infos` as an equivalent Syft-shaped BOM whose root is in `components`. |
| DG-EX-14 | **Roots (Q4).** (a) Two unreferenced entries with children in one BOM: both are roots, children unioned, one `MULTIPLE_ROOTS` warning whose `subjects` are the two bom-refs, sorted; the orphan-library case drops that library from the node set (documented behaviour). (b) An unreferenced entry with empty `dependsOn` stays a node, with no warning. (c) No root entry: `ROOT_NOT_FOUND`, nodes present, none reachable. |
| DG-EX-15 | **Example paths (D6).** A diamond `root → a → c`, `root → b → c`, plus `root → a → x → c`: `c.example_paths` with K=3 is `(("a","c"), ("b","c"))` (the longer path is excluded); K=1 gives `(("a","c"),)`; K=0 gives `()`. If a second service reaches `c` directly, `c`'s only example path is the one-node path of the second service. |
| DG-EX-16 | **Witnesses (D13).** For `t` in DG-EX-8: with K=0, `path_witnesses` still has two entries, `(runtime, transitive)` via `r` and `(dev, transitive)` via `d`. For a node that is both a dev direct dependency and a runtime transitive one, the `(dev, direct)` witness is the one-node path and the `(runtime, transitive)` witness runs through the runtime dependency even when the K shortest paths are all one node. When the K shortest paths are all runtime, the `(dev, …)` witness is still present. |
| DG-EX-17 | **Depth cap (D15).** A chain of 70 nodes with `max_path_nodes=64`: nodes at depth ≤ 64 have paths; deeper nodes have none, correct `path_infos`, and the graph carries one `PATHS_OMITTED` warning. |
| DG-EX-18 | **`package-lock.json` per-package scope.** `lock_npm.json`: all keys `runtime`; every Syft-npm node key is a key of `package_scopes`. Real, with dev and optional: `lock_npm_dev.json`: `is-number` is `dev`; `left-pad` and `uuid` are `runtime` (`optional` does not make a package dev); expectations are recomputed from the file's own `dev` / `optional` flags by independent code. Synthetic: `lock_npm_edge.json` covers `devOptional: true` (runtime, D12); `peer: true` (runtime); nested `node_modules/a/node_modules/@s/b`; an alias with `name`; a `link: true` entry (skipped); a package present twice, one dev and one runtime (runtime). A v1-shaped document (built inline) raises. |
| DG-EX-19 | **`package-lock.json` declared scope (D11).** `lock_npm.json`: `direct_scopes` has `express`, `JSONStream`, `moment`, `request`, all runtime, and every direct dependency of the Syft root is a key of it (parity). Real: `lock_npm_dev.json`: `direct_scopes` is `runtime` for `left-pad` and `uuid` (a name in `optionalDependencies` is runtime) and `dev` for `is-number`; no warnings; no `DIRECT_UNRESOLVED`. Synthetic: `lock_npm_edge.json`: a name in `dependencies`, `optionalDependencies` or `peerDependencies` is runtime; a `devDependencies`-only name is dev; a name in both is runtime; a declared name with no `node_modules/<name>` entry yields `DIRECT_UNRESOLVED`; a devDependency whose entry has no `dev` flag (production also requires it) emits **no** warning and keeps `dev` in `direct_scopes`; a runtime declaration whose entry has `dev: true` yields exactly one `SCOPE_DISAGREEMENT` and keeps `runtime` in `direct_scopes`. With that scope result, `build_graph` gives the silent devDependency `(dev, direct)` plus `(runtime, transitive)` when a runtime dependency requires it. |
| DG-EX-20 | **`poetry.lock`.** Real: `lock_poetry.toml` (generated by Poetry): the main dependency is `runtime`, the dev dependency is `dev`, according to the markers the tool wrote; `direct_scopes` is empty; no warnings; keys equal `pypi_key(name, version)` for the file's own `name`/`version` fields. Synthetic: `lock_poetry_edge.toml`: `groups = ["main"]` ⇒ runtime; `["dev"]` and `["dev", "test"]` ⇒ dev; `["main", "dev"]` ⇒ runtime; legacy `category = "main"` / `"dev"`; neither field ⇒ runtime; name normalisation (`Flask_SQLAlchemy` ⇒ `pypi/flask-sqlalchemy@…`). |
| DG-EX-21 | **`uv.lock`.** Real, with a dev group: `lock_uv_backend.toml`: the project package `graveyard-backend` is absent from both maps; `direct_scopes` is `runtime` for `packageurl-python` and `pyyaml` and `dev` for `hypothesis`, `mypy`, `pytest`, `pytest-cov`, `ruff` and `types-pyyaml`; `package_scopes` has 20 keys, 2 `runtime` and 18 `dev` (every transitive package is reachable only through the dev group, e.g. `coverage`, `sortedcontainers`, `typing-extensions`); no warnings; key parity with `pypi_key` on the file's own fields. Real, runtime only: `lock_uv.toml`: every non-project package is `runtime`, `direct_scopes` holds `nose`, `requests`, `six`, every Syft-py node key is a key of `package_scopes`. Synthetic: `lock_uv_edge.toml`: a package reachable from both a runtime and a dev seed (runtime); an optional-dependency target (runtime); a cycle among dev packages (dev, terminates); a name resolving to two versions; a reference that resolves to nothing (`DIRECT_UNRESOLVED`); a package reachable from no seed (runtime). |
| DG-EX-22 | **`requirements.txt`.** Pinned lines with extras, marker, trailing comment, hashes with `\` continuation, CRLF line endings, a leading BOM. Skipped silently: `-r other.txt`, `-e .`, `# comment`, blank lines. Skipped with `REQUIREMENT_SKIPPED`: `git+https://…`, `requests>=2`, `flask==1.*`, `./local`. |
| DG-EX-23 | **End to end.** `parse_uv_lock` + `build_graph([ServiceInput("py", syft_py, scopes)])` on the real fixtures yields no `SCOPE_ASSUMED` warning and the same `path_infos` as DG-EX-1. `parse_package_lock` + `build_graph` on the npm fixtures yields no `SCOPE_ASSUMED`. |
| DG-EX-24 | **Parser warnings reach the graph.** A `ScopeResult` carrying a `SCOPE_DISAGREEMENT` appears in `graph.warnings` with `service` set to the service path. |

---

## Invariants: property-based test requirements

Each invariant is a Hypothesis test tagged `@pytest.mark.property`, run under the `dev` (200) and `ci` (500) profiles (`HYPOTHESIS_PROFILE`). Shared strategies live in `tests/strategies.py`; the oracle in `tests/oracle.py`.

### Strategies and oracle

- `abstract_services()`: 1–3 services, each with a root, 0–8 package nodes drawn from a pool of ≤ 8 abstract nodes shared across services (so dedupe happens), arbitrary edges including self-loops, 2-cycles and longer cycles (edge density drawn from sparse, medium and dense), arbitrary direct-dependency subsets, and a scope per direct dependency per service.
- `render(abstract)`: renders each service as a CycloneDX 1.5/1.6/1.7 dict in the Syft shape and a matching `ScopeResult`. It randomises: `specVersion`; `?package-id=<hex>` suffixes; npm names in mixed case so that `purl` and `bom-ref` differ in case; a `type: file` component; a `metadata.component` with a directory-hash bom-ref; whether scope comes from `direct_scopes`, from `package_scopes` only, or is absent (D8/D11 fallbacks); and the order of every list. Duplicates (components, entries, `dependsOn` elements) come from a separate flag so DG-DUP-2 can be tested.
- `shuffled(bom, seed)`: reorders components, nested components, dependency entries and `dependsOn`, and the key order of every object and every `ScopeResult` map.
- `oracle`: **independent**, shares no code with `core.graph`. By plain recursive DFS over the abstract graph (≤ 8 nodes), it enumerates **all simple paths** from each root. For each path it emits `(end node, PathInfo(scope[path[0]] == "runtime", len(path) == 1))`, the service, and the length. From these it derives per node: the `PathInfo` set, the services with a path, the minimum path length, the minimum length per `PathInfo` member, and the set of minimum-length paths. It SHALL NOT use SCCs, BFS, or any helper imported from `core.graph`.

### DG-INV-1: Deterministic output regardless of input order

For any `abstract_services()` and any two shufflings of the rendered input (service order, component order, edge order, mapping key order), `build_graph` returns equal results, `graph_to_dict` results are equal, and `json.dumps` of them is byte-identical (DG-OUT-1, DG-OUT-2, DG-ROOT-5). This covers `warnings`, `example_paths` and `path_witnesses`.

### DG-INV-2: Dedupe is idempotent and key-based

- Duplicating components, dependency entries and `dependsOn` elements in a rendered BOM leaves the result equal (DG-DUP-2).
- Different bom-ref suffixes and different npm case for the same abstract node yield one node; the number of nodes equals the number of distinct abstract nodes present in some service (DG-DUP-1, D1).
- `GraphNode.purl` is independent of input order (DG-DUP-3).

### DG-INV-3: Every example and witness path is a real path from a root

For every node and every path (in `example_paths` and `path_witnesses`) in service `s`: `nodes[0]` is a direct dependency of `s`'s root; `nodes[-1] == node.key`; each consecutive pair is an edge of `s` in the abstract graph; `len(set(nodes)) == len(nodes)`; `len(example_paths) ≤ K`; example paths are distinct and sorted per DG-PATH-3. K ∈ {0, 1, 2, 3, 5}.

### DG-INV-4: `path_infos` equals the brute-force oracle

On small random graphs (≤ 8 nodes per service, cycles allowed, 1–3 services), `{n.key: set(n.path_infos)}` equals the oracle's set for **every** node, including those with an empty set. A sanity test (`test_oracle_sanity.py`) runs a deliberately naive implementation (plain reachability that counts a node's own cycle as a transitive path) against the oracle on explicit trap graphs and asserts that the oracle distinguishes it, so the oracle is known to be able to see D5.

### DG-INV-5: Termination on cycles

For strongly connected graphs, graphs with self-loops, graphs with cycles through direct dependencies, and the complete digraph on 8 nodes, `build_graph` returns within the explicit Hypothesis deadline (DG-NFR-7). Example test: the complete digraph on 200 nodes finishes within DG-NFR-1, which no path-enumerating implementation could do.

### DG-INV-6: Unreachable nodes have no `PathInfo`

If the oracle finds no simple path to a node in any service, then `path_infos == ()`, `services_affected == 0`, `example_paths == ()`, `path_witnesses == ()`, `direct` and `transitive` are false and `scope is None`. Generation includes components with no inbound edges and services with no root entry.

### DG-INV-7: Services affected and manifests

`services_affected` equals the oracle's count of services with at least one path to the node; it is ≤ the number of services, and 0 iff `path_infos` is empty (DG-SVC-1, DG-SVC-2). `manifests` equals the set of services whose BOM contains the node, whether or not it is reachable.

### DG-INV-8: Example paths are shortest; witnesses are minimal and cover every member

- Each example path's length equals the oracle's minimum simple-path length to the node over all services, and the paths equal the first `min(K, count)` of the oracle's minimum-length paths in the DG-PATH-3 order.
- `path_witnesses` has exactly one entry per `path_infos` member (default `max_path_nodes`), each with the PathInfo of DG-WIT-2, each of length equal to the oracle's minimum length for that member.
- The witness for `(runtime, direct)` / `(dev, direct)` is the one-node path.

### DG-INV-9: Monotonicity

Adding an edge or a direct dependency to an abstract graph never removes a member of any node's `path_infos` and never decreases `services_affected`. Changing a direct dependency's scope from `dev` to `runtime` never removes a `runtime=True` member.

### DG-INV-10: Scope parsers

- **Rendered round trip.** Strategies render an abstract package list as `package-lock.json` (with a root entry), `poetry.lock` (v1 and v2 shapes), `uv.lock` (with a project package) and `requirements.txt` text, and the parser output equals the expected maps, computed independently in the test (for `uv.lock`, by a plain-Python closure written in the test).
- **Any wins.** For `package-lock.json` with duplicated entries, the per-package scope is `runtime` iff any entry is runtime. For `uv.lock`, adding a runtime seed pointing at a package never turns it from runtime to dev.
- **devOptional is runtime.** Generated entries with `devOptional: true` are never `dev`.
- **Declared vs per-package.** For generated `package-lock.json` text, a package gets exactly one `SCOPE_DISAGREEMENT` warning if and only if it is declared `runtime` in `packages[""]` and its per-package scope is `dev`. A package declared `dev` never gets one, whatever its per-package scope. For generated `uv.lock` text there is never one.
- **Totality.** For arbitrary `str` input (Hypothesis `text()` including surrogates, and mutated valid documents) every parser returns a `ScopeResult` or raises `ValueError`, and nothing else; `parse_requirements_txt` never raises.
- **Order and whitespace independence.** Shuffling `[[package]]` tables, JSON object keys or requirements lines, and changing line endings (`\n`, `\r\n`), does not change the result.
- **Key parity.** Every generated package's key equals `package_key(parse_purl(...))` of the equivalent purl, including `JSONStream`-style upper-case npm names (folded) and `Flask_SQLAlchemy`-style PyPI names (PEP 503).
- **Linear time.** A 100,000-character line of pathological requirement text parses within the NFR budget.

### DG-INV-11: Robustness of ingest

For arbitrary JSON-shaped values (Hypothesis recursion over `None`, bool, int, float, str, list, dict) and for rendered BOMs mutated by deleting, retyping or nulling one field, `build_graph` either returns a `DependencyGraph` or raises `ValueError`. It never raises another exception type and never hangs (DG-OUT-4).

### DG-INV-12: Warnings are well-formed

For every generated input, including mutated and over-limit ones: every `code` is in `WARNING_CODES`; warnings are sorted, unique, and within the cap; `subjects` are sorted and within `MAX_SUBJECTS`; no text exceeds `MAX_TEXT`; a `MULTIPLE_ROOTS` warning lists exactly the oracle's root candidates; `SCOPE_ASSUMED` appears for a service iff at least one of its direct dependencies had neither a declared nor a per-package scope. Nothing is written to stdout, stderr or any logger (checked with `capsys` and `caplog` in a non-Hypothesis wrapper test over a fixed sample, since function-scoped fixtures do not mix with `@given`).

---

## Review decisions (round 1)

1. **Root in example paths.** The root is excluded and `service` is carried separately (D7).
2. **K shortest plus witnesses.** `example_paths` keeps up to K minimum-length paths; every `PathInfo` member also gets one witness in `path_witnesses` (≤ 4 extra), independent of K (D13). The witnesses are minimum-length among their kind, so the UI can explain runtime and direct even when all K shortest are one kind.
3. **Export property.** "Ingest → export → ingest is a fixed point" moves to the future `coroners-report` spec; `testing.md` and PRD §11.6 say so (D16).
4. **Multiple roots.** All root candidates are kept; anomalies are reported as structured `GraphWarning`s in the result, and the module never logs (D14, DG-WARN-*).
5. **`devOptional`.** Treated as runtime (D12, DG-SCP-1, DG-EX-18).
6. **Direct-edge scope.** Taken from the lockfile's declaration of the project's dependencies (`packages[""]`; the project entry in `uv.lock`), not from `package.json`. Per-package flags are a cross-check that raises `SCOPE_DISAGREEMENT` only when a package is declared runtime and flagged dev-only (D11, DG-SCP-4, DG-SCP-5, DG-SCP-9; narrowed in round 2).
7. **npm fixture.** A task re-records the npm SBOM with Syft 1.56.0, scrubs paths, and uses it as the fixture (DG-NFR-6, Fixtures).

### Added while applying the decisions

- **Root rule refined (DG-ROOT-1).** An unreferenced `dependencies` entry with an empty `dependsOn` is an orphan, not a root, so a stray leaf cannot be promoted and dropped from the node set.
- **Scope result type.** The parsers return `ScopeResult` (per-package scopes, declared direct scopes, warnings) instead of a bare map, because decisions 4 and 6 need the extra two fields.
- **Witness algorithm.** `path_infos` and witnesses both come from a bounded two-origin breadth-first search per scope (design §5.3). It needs no strongly-connected-component pass.
- **Result-size cap (D15).** Added because witnesses and example paths on a very deep chain would otherwise grow quadratically.
- **Example path order (D6).** Defined by reading the path from the node backwards, which makes lazy enumeration linear.

### Residual risks

- A workspace `uv.lock` merges the dependencies of every member into one `direct_scopes`. A service that corresponds to a single member may therefore get a declared scope from a sibling. Accepted for v1; the fallback to `package_scopes` is unaffected.
- `SCOPE_DISAGREEMENT` now signals an inconsistent lockfile and should be rare. The common case (a devDependency that production also requires) is silent and shows up only as the extra `(runtime, transitive)` member of the node's `path_infos`.
- Poetry cannot supply `direct_scopes`, so a dev-declared package that production also reaches is reported `runtime` for its direct edge. Conservative for exposure.

---

## Review decisions (round 2)

1. **`SCOPE_DISAGREEMENT` is one-directional.** It fires only when a direct dependency is declared `runtime` (`packages[""]`, or the uv project entry) while its per-package scope is `dev`. Declared `dev` with per-package `runtime` emits nothing (D11, DG-SCP-5, DG-EX-19, DG-INV-10).
2. **Real lockfiles replace synthetic ones where a tool can produce them.** `lock_uv_backend.toml` is a frozen copy of the real `backend/uv.lock` (it has a dev group). `lock_poetry.toml` is generated by pinned `uvx --from poetry==<latest> poetry lock` on a tiny project with one main and one dev dependency; the task stops and asks if that fails. Hand-written fixtures remain only for cases a real tool cannot produce, labelled synthetic (Fixtures, DG-EX-20, DG-EX-21). `lock_uv_dev.toml` is replaced by `lock_uv_edge.toml`, and `lock_poetry_v1.toml` / `lock_poetry_v2.toml` by `lock_poetry_edge.toml`.

---

## Review decisions (round 3)

1. **npm gets a real fixture too.** `lock_npm_dev.json` is generated by `npm install --package-lock-only --ignore-scripts` in a scratch directory outside the repo, for a `package.json` with `left-pad` 1.3.0 (dependency), `is-number` 7.0.0 (devDependency) and `uuid` 3.4.0 (optionalDependency). It exercises `dev`, `optional` and all three of the root entry's dependency groups. The hand-written npm file is renamed `lock_npm_edge.json` and keeps only what npm will not produce from a small project: `devOptional`, aliases, workspace links, nested duplicates, a devDependency that production also requires, a runtime declaration flagged `dev`, and a name in both dependency groups (Fixtures, DG-EX-18, DG-EX-19).
