# Spike Findings

> Throwaway validation scripts in `spikes/` (PEP 723, `uv run`). Run on 3 Nov 2026.
> Packages tested — npm: request, node-uuid, moment, express, left-pad, uuid; PyPI: pycrypto, nose, requests, pycryptodome, six.
> Sources called: deps.dev v3 (package, version, project), OSV `/v1/querybatch`, npm registry, PyPI JSON API. Syft v1.56.0.

## Summary Table

| # | Question | Finding | Evidence | Decision needed |
|---|----------|---------|----------|------------------|
| 1 | Signal coverage: which of S1–S9 are obtainable per package, and which source provides each? | S2, S7 obtainable for all 11 packages. S1/S1b obtainable for npm via deps.dev + npm registry (6/6). S4, S6 (partial), S8 obtainable for 9/11 (missing pycrypto, nose — no SOURCE_REPO link). S3, S5 not obtainable from any tested source. S9 dependents count not available anywhere; only stars/forks proxies from deps.dev. | See per-signal table below. | GitHub GraphQL needed for S3 and S5; ecosyste.ms or GitHub stats API for S9 dependents. For PyPI packages without a SOURCE_REPO link in deps.dev (pycrypto, nose), fall back to GitHub repo URL from PyPI `project_urls` to fetch Scorecard directly. |
| 2 | npm deprecation: is `deprecated` set on the latest version, only on older versions, or neither? | S1 (latest deprecated): request, node-uuid, left-pad. S1b (only older versions): moment (2 broken versions), express (173, 0.x/1.x series), uuid (38, v10 and below). Neither: 0 packages. | deps.dev `isDeprecated` on default version + npm registry `deprecated` field. Both sources agree. | Confirms S1 vs S1b distinction is well-supported by both deps.dev and npm registry. Use deps.dev as primary (already has `isDefault` flag); npm registry as fallback. |
| 3 | PyPI status: does the JSON API expose project status (PEP 792) or the "Development Status :: 7 - Inactive" classifier? | Neither. No PEP 792 status field exists in the PyPI JSON API response. No package has the "7 - Inactive" classifier — all five report "5 - Production/Stable", including dead packages (pycrypto last released 2014, nose last released 2015). The `yanked` field exists but is false for all. | Full `info` keys enumerated: no key contains "status", "archiv", or "deprecat". Classifiers checked for all 5 packages. | S1 for PyPI cannot come from PyPI itself. Use deps.dev Scorecard Maintained=0 with reason "project is archived" as a proxy (works for packages with a GitHub repo). Alternatively, check the GitHub repo `archived` flag via GraphQL. PyPI death detection must rely on GitHub-side signals + staleness. |
| 4 | Scorecard via deps.dev: are Maintained and overall scores present? Do any return -1? Does deps.dev give a dependents count? | Maintained and overall scores present for 9/11 packages (all with a SOURCE_REPO link). Missing for pycrypto and nose (no SOURCE_REPO in deps.dev version metadata). Multiple individual checks return -1 (Packaging, Signed-Releases, Branch-Protection, Dangerous-Workflow, Token-Permissions, Pinned-Dependencies). overallScore is never -1 — always a positive float when present. deps.dev v3 has NO dependents endpoint; it provides openIssuesCount, starsCount, forksCount only. | deps.dev `/v3/projects/{id}` (URL-encoded project key). Checks returning -1: express (Packaging, Signed-Releases, Branch-Protection), node-uuid (5 checks), left-pad (5 checks), uuid (Branch-Protection, Signed-Releases), requests (Branch-Protection), pycryptodome (Packaging). | Treat -1 as "inconclusive/missing" per PRD §7.2. For dependents count, use ecosyste.ms or npm downloads API / pypistats as a separate source. Handle packages without SOURCE_REPO by trying the registry's `repository` field or PyPI `project_urls` to construct the project key. Note: SOURCE_REPO URL formats vary (`git+https://github.com/...`, `github:owner/repo`). |
| 5 | Syft: does CycloneDX JSON include dependency relationships (direct vs transitive)? | Yes. Syft v1.56.0 CycloneDX 1.7 JSON includes a `dependencies` array with `dependsOn` relationships. The fixture/project component appears in both `components` and `dependencies`, listing its direct deps. Transitive deps appear in the `dependsOn` of other components. npm: 114 components, 46 dependency entries (fixture → express, moment, request; express → 32 sub-deps; request → 21). PyPI: 9 components, 2 dependency entries (fixture → nose, requests, six; requests → certifi, charset-normalizer, idna, urllib3). Direct vs transitive IS distinguishable from the SBOM. | `syft dir:{path} -o cyclonedx-json` on npm fixture (express, request, moment) and PyPI fixture (requests, six, nose). Lockfiles: `npm install --package-lock-only --ignore-scripts` and `uv lock`. Raw BOMs saved to `spikes/npm-sbom.cdx.json` and `spikes/py-sbom.cdx.json`. | Syft is viable for lockfile → SBOM (PRD EX-S1). The root component's `bom-ref` in `metadata.component` is a directory hash, NOT the project's purl — match on the fixture's component `bom-ref` in the `components` array instead. Components have no `scope` field; all found by `javascript-lock-cataloger`. No code modification needed vs. custom parsers. |

## Q1 Per-Signal Detail

| Signal | Source | npm coverage | PyPI coverage | Notes |
|--------|--------|-------------|---------------|-------|
| **S1** Declared death | deps.dev `version.isDeprecated` + npm registry `deprecated` | 6/6: request ✓, node-uuid ✓, left-pad ✓ (deprecated on latest); moment ✗, express ✗, uuid ✗ | 0/5: PyPI has no deprecation/status field; no "7 - Inactive" classifier | deps.dev `isDeprecated` and npm registry `deprecated` agree. For PyPI, detect via Scorecard Maintained=0 reason "project is archived" or GitHub GraphQL. |
| **S1b** Version deprecated | deps.dev `isDeprecated` (non-default) + npm registry | 6/6: all have older deprecated versions (request: 125, express: 173, uuid: 38, left-pad: 14, node-uuid: 13, moment: 2) | N/A (PyPI has no deprecation mechanism) | Validated: deprecating only older versions is S1b, not S1. |
| **S2** Release staleness | deps.dev `publishedAt` + npm registry `time[latest]` + PyPI `releases[latest].upload_time` | 6/6 ✓ | 5/5 ✓ | All sources provide release timestamps. deps.dev and npm registry agree to the second for npm. |
| **S3** Commit staleness | — | 0/6 (NOT available) | 0/5 (NOT available) | Requires GitHub GraphQL `pushedAt`. None of the 4 tested sources provide this. |
| **S4** Maintained check | deps.dev `project.scorecard.checks[Maintained]` | 6/6: request=0, node-uuid=0 (archived), moment=10, express=10, left-pad=0 (archived), uuid=9 | 3/5: requests=10, pycryptodome=5, six=0; pycrypto & nose missing (no SOURCE_REPO) | Scorecard Maintained score 0 + reason "project is archived" indirectly signals S1 for archived repos. |
| **S5** Bus factor | — | 0/6 (NOT available) | 0/5 (NOT available) | Requires GitHub stats or ecosyste.ms. None of the 4 tested sources provide committer counts. |
| **S6** Issue neglect | deps.dev `openIssuesCount` (partial) | 6/6 (partial): openIssues only; no closed count, no response time | 3/5 (partial): requests=245, pycryptodome=58, six=114; pycrypto & nose missing | Only open issue count available from deps.dev. Full S6 (open/closed ratio, median response time) needs GitHub GraphQL. |
| **S7** Vulnerabilities | OSV `/v1/querybatch` + deps.dev `advisoryKeys` | 6/6: request@2.88.2 has 1 vuln (fix available); all others 0 | 5/5: pycrypto@2.6.1 has 4 vulns (2 with no fix → Cursed); all others 0 | OSV gives full advisory details (fix ranges). deps.dev `advisoryKeys` gives IDs only; use OSV as primary. One batch query per scan (≤1000 queries) per PRD. |
| **S8** Scorecard overall | deps.dev `project.scorecard.overallScore` | 6/6: 2.0–8.5 (request=3.4, node-uuid=2.0, moment=6.1, express=8.5, left-pad=3.9, uuid=4.4) | 3/5: 3.7–8.2 (requests=8.2, pycryptodome=5.2, six=3.7); pycrypto & nose missing | Never -1. Missing when no project (no SOURCE_REPO). |
| **S9** Dependents / popularity | deps.dev: NOT available (no dependents endpoint in v3) | 0/6 dependents; 6/6 stars+forks proxies | 0/5 dependents; 3/5 stars+forks proxies | deps.dev provides `starsCount` and `forksCount` as popularity proxies, not dependents. Use ecosyste.ms or npm downloads API / pypistats for true dependents/download counts. |

## Q2 npm Deprecation Detail

| Package | Latest version | Deprecated on latest? | Older versions deprecated | Count | Verdict |
|---------|---------------|----------------------|--------------------------|-------|---------|
| request | 2.88.2 | YES — "request has been deprecated, see https://github.com/request/request/issues/3142" | YES | 125 | **S1** (declared death) |
| node-uuid | 1.4.8 | YES — "Use uuid module instead" | YES | 13 | **S1** (declared death) |
| moment | 2.31.0 | NO | YES (broken versions only) | 2 | **S1b** (upgrade advised) |
| express | 5.3.0 | NO | YES (0.x and 1.x series) | 173 | **S1b** (upgrade advised) |
| left-pad | 1.3.0 | YES — "use String.prototype.padStart()" | YES | 14 | **S1** (declared death) |
| uuid | 14.0.3 | NO | YES (uuid@10 and below) | 38 | **S1b** (upgrade advised) |

## Q3 PyPI Status Detail

| Package | PEP 792 status field? | "7 - Inactive" classifier? | Actual classifier | `yanked` | Latest upload |
|---------|----------------------|---------------------------|------------------|----------|---------------|
| pycrypto | No | No | 5 - Production/Stable | false | 2014-06-20 |
| nose | No | No | 5 - Production/Stable | false | 2015-06-02 |
| requests | No | No | 5 - Production/Stable | false | 2026-05-14 |
| pycryptodome | No | No | 5 - Production/Stable | false | 2026-11-02 |
| six | No | No | 5 - Production/Stable | false | 2024-12-04 |

## Q4 Scorecard -1 Checks

| Check | Packages returning -1 | Notes |
|-------|----------------------|-------|
| Packaging | express, node-uuid, left-pad, pycryptodome | "packaging workflow not detected" |
| Signed-Releases | express, node-uuid, left-pad, uuid | "no releases found" |
| Branch-Protection | express, node-uuid, left-pad, uuid, requests | "internal error" (token permissions) |
| Dangerous-Workflow | node-uuid, left-pad | (archived repos) |
| Token-Permissions | node-uuid, left-pad | (archived repos) |
| Pinned-Dependencies | node-uuid, left-pad | (archived repos) |
| **overallScore** | **none** | Always a positive float when present; never -1 |

## Q5 Syft Output Detail

| Fixture | Components | Dependency entries | Root → direct deps | Direct deps | Transitive deps | Verdict |
|---------|-----------|-------------------|-------------------|-------------|----------------|---------|
| npm (express, request, moment) | 114 | 46 | fixture → express, moment, request | 3 (express, moment, request) | 111 | YES — relationships present |
| pypi (requests, six, nose) | 9 | 2 | fixture → nose, requests, six | 3 (nose, requests, six) | 6 (certifi, charset-normalizer, idna, urllib3, + 2) | YES — relationships present |

Notes: The fixture/project component appears in both `components` and `dependencies` arrays. Its `dependsOn` lists the direct dependencies. Transitive deps appear in the `dependsOn` of other (non-fixture) components. The `metadata.component.bom-ref` is a directory hash, not the project purl — use the fixture's `bom-ref` from the `components` array to find the root dependency entry. Components have no `scope` field; npm components all share `foundBy: javascript-lock-cataloger`.

### Q5 addendum, re-recorded 9 Nov 2026

The npm row above predates `JSONStream` (114 components, 3 root children). `spikes/npm-sbom.cdx.json` was re-recorded against the current `spikes/fixtures/npm` (116 lockfile entries, `JSONStream` pinned at 1.3.5). The `py` row is unchanged.

- Syft 1.56.0, run from the repo root: `SYFT_CHECK_FOR_APP_UPDATE=false ~/.local/bin/syft dir:spikes/fixtures/npm -o cyclonedx-json=spikes/npm-sbom.cdx.json`. Syft only reads files. Output is Syft's own compact JSON (one line), not the `indent=2` form `05_syft.py` writes.
- Then one exact-string edit: `metadata.component.name` `spikes/fixtures/npm` → `fixtures/npm` (DG-NFR-6). Nothing else was edited.

| Figure | Value |
|---|---|
| `library` components | 116 (115 packages + the project component) |
| `file` components | 1 (`/package-lock.json`) |
| `dependencies` entries | 47 |
| Root `bom-ref` | `pkg:npm/graveyard-spike-npm-fixture@0.0.1?package-id=3491eba9e54c1ca3` |
| `metadata.component.bom-ref` | `6fb2060e44576377` (in neither `components` nor `dependencies`) |
| Root children | 4: `express`, `JSONStream`, `moment`, `request` |
| Distinct `(source key, target key)` edges, root excluded | 193 |
| Root edges | 4 |
| Nodes reachable from the root | 115 (all packages) |

Versus the old BOM: new components `JSONStream`, `jsonparse`, `through`; 47 dependency entries instead of 46 (`JSONStream`); the project component's `package-id` and the `metadata.component.bom-ref` changed (Syft derives them from content); the `/package-lock.json` file hashes changed; new `serialNumber` and `timestamp`. No other component changed. The `package-id` values quoted in the requirements (`79a003f4bd8db3e1`, `8fb02136c12967a7`) describe the superseded recording.

## Q6 — npm purl case in Syft output

| Syft version | Command | Component | `purl` emitted | `bom-ref` emitted | Observed case |
|---|---|---|---|---|---|
| 1.56.0 | `syft dir:spikes/fixtures/npm -o cyclonedx-json` | `JSONStream` 1.3.5 (fixture pins `"JSONStream": "1.3.5"`; found by `javascript-lock-cataloger`) | `pkg:npm/JSONStream@1.3.5` | `pkg:npm/jsonstream@1.3.5?package-id=32a65e0552e1b113` | `purl` keeps `JSONStream`; `bom-ref` is lower-case `jsonstream` |

Notes: `name` is `JSONStream`. The `purl` and the `bom-ref` spell the same package with different case, so dedupe on either one needs ASCII case folding for npm (`package_key`). The `package-id` suffix is a Syft hash and not part of the purl. Component saved as `backend/core/purl/tests/fixtures/syft_jsonstream.json`.

## Q7 — Syft and dev dependencies, run against the CLI fixture project (11 Nov 2026)

Found by the first real-Syft run of `graveyard autopsy` (spec `graveyard-cli`, T11.3). The CLI's fixture project (`backend/cli/tests/fixtures/anchors-project/`) has a `package-lock.json` with two `dev: true` packages (`request`, `uuid`) and a `uv.lock` whose dev group holds `nose`. Syft 1.56.0, `syft dir:<service> -q -o cyclonedx-json`.

| Question | Finding |
|---|---|
| Does Syft list the `dev: true` packages of a `package-lock.json`? | **No, by default.** `web` gave 5 library components (the project, `express`, `left-pad`, `moment`, `node-uuid`); `request` and `uuid` were absent. With `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true` it gave 7, including `request` and the edge `request -> uuid`. |
| Does Syft link the project root to its dev direct dependencies? | **No, with or without the variable.** In both real documents the root `dependsOn` lists only the runtime directs. `request` (npm `devDependencies`) and `nose` (uv dev group) have no incoming edge. `nose` is listed as a component even by default; the uv cataloguer includes dev groups. |
| What does `core.graph` make of that? | `request` has edges of its own (`request -> uuid`) and nothing depends on it, so it matches the root rule (an unreferenced `dependencies` entry with targets) and becomes a **second root**: `MULTIPLE_ROOTS`, `request` dropped as a package, `uuid` read as a direct dependency. `nose` has no entry, so it is a node with no path: its exposure is assumed (the highest weight). |
| Where do absolute paths appear? | Only in `metadata.component.name` (the scanned directory). The fixtures replace it by `fixtures/web` or `fixtures/api`. |

Consequences:

- The CLI starts Syft with `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true` (and `SYFT_CHECK_FOR_APP_UPDATE=false`), set by `cli/syft.py`.
- The CLI adds `root -> direct` edges for every direct dependency the lockfile declares and the root does not already reach (`cli/augment.py`), before the graph is built. The root is the one unreferenced entry whose package is not itself a declared direct dependency; for a project with only dev dependencies it is `metadata.component`.
- The EX-8 premise "Syft gives no scope, so read it from the lockfile" holds, and also covers the edges: for dev dependencies the lockfile is the only source of "the project declares this".
- An unreadable lockfile leaves nothing to augment from, so the problem above returns for that service (`MULTIPLE_ROOTS`); the CLI reports it and continues.
- The hand-written, Syft-shaped SBOMs the CLI tests first used encoded the opposite assumption (an edge from the root to each dev direct). They were replaced by real output, and an opt-in contract test (`pytest -m syft`) runs the real binary.
- The same applies to any other tool that feeds the pipeline from a Syft SBOM, for example the Lambda in the `infra-serverless` spec: set the variable in the container environment and apply the same edges.

## KP-S1 — What a Pre Tool Use hook receives and whether exit 2 blocks (2026-11-11)
Spec `kiro-power`, T1. A throwaway `PreToolUse` command hook (matcher `shell`) wrote its raw stdin and the environment variable names to a scratch directory, and exited 2 when stdin held a sentinel. Kiro 1.4.86 (commit `853cde3b3bed4d25550ec316e5272a435d3bb86c`, arm64, macOS), read with `kiro --version` from the CLI launcher; not checked against the About dialog. Tool name seen by the hook: `execute_bash` (the matcher `shell` matched it).
Payload: top-level keys `session_id`, `hook_event_name` (`"PreToolUse"`), `cwd`, `tool_name`, `tool_input`. `cwd` equals the workspace root. `tool_input` keys: `command` (string, the full text including multi-line commands), `description`, `cwd`, `run_in_background` (bool), `timeout`. In the sample the three of those that are not `command` or `run_in_background` were null. The payload has no trailing newline.
Redacted sample:
```json
{"session_id":"<SESSION_ID>","hook_event_name":"PreToolUse","cwd":"<WORKSPACE_ROOT>","tool_name":"execute_bash","tool_input":{"command":"echo kp-s1-harmless","description":null,"cwd":null,"run_in_background":false,"timeout":null}}
```
Other observations:
- Stdin was closed after the write: `cat` returned and the capture is complete, valid JSON.
- No environment variable carries the tool call (no `TOOL_*`, `HOOK_*` or command variable). `KIRO_SESSION_ID` and `VSCODE_*` names exist. The probe's own working directory was the workspace root.
- Exit 2 blocked the call: the marker file was not created. The model received a message saying the call was intercepted by PreToolUse hooks and not executed, containing the probe's one stderr line (`graveyard kp-s1 probe: sentinel blocked`) wrapped in tool text. No stderr label and no exit code were shown. A capture exists for the blocked call.
### Observed fields
| Field | Observed |
|---|---|
| `COMMAND_FIELD` | `command` (in `tool_input`) |
| `CWD_FIELD` | `cwd` (top-level envelope; `tool_input.cwd` exists but was null) |
| `tool_name` | `execute_bash` |
| `stdin closed` | yes |
| `exit 2 blocks` | yes |
| `stderr reaches the model` | yes (wrapped in tool text) |
### Unmeasured
- Exit 1 behaviour: not documented, not measured.
- Hook timeout behaviour: not documented, not measured.
- Unapproved `${VAR}` expansion: not documented, not measured.
- MCP server working directory: not documented, not measured.
- Types of non-null `tool_input.cwd`, `tool_input.timeout` and `tool_input.description`: not documented, not measured.
