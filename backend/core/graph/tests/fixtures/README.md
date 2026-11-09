# Fixtures for `core/graph`

Paths in the **Command** column are relative to the repo root. No fixture contains a local path (DG-NFR-6). Syft only reads files; nothing was installed or executed to produce these.

| File | Source | Command | Tool version | Date | Kind |
|---|---|---|---|---|---|
| `syft_npm.cdx.json` | `spikes/fixtures/npm` (lockfile with `JSONStream`, 116 entries); identical to `spikes/npm-sbom.cdx.json` | `SYFT_CHECK_FOR_APP_UPDATE=false ~/.local/bin/syft dir:spikes/fixtures/npm -o cyclonedx-json=spikes/npm-sbom.cdx.json`, then one exact-string edit: `metadata.component.name` `spikes/fixtures/npm` → `fixtures/npm` | Syft 1.56.0 | 2026-11-09 | recorded |
| `syft_py.cdx.json` | `spikes/py-sbom.cdx.json` (recorded 2026-11-03 from `spikes/fixtures/py`) | one exact-string edit: `metadata.component.name` the author's absolute path to `spikes/fixtures/py` → `fixtures/py` | Syft 1.56.0 | 2026-11-09 (copy) | recorded |
| `lock_npm.json` | `spikes/fixtures/npm/package-lock.json` (byte copy) | `cp` | npm lockfile, as committed | 2026-11-09 (copy) | recorded |
| `lock_uv.toml` | `spikes/fixtures/py/uv.lock` (byte copy) | `cp` | uv lockfile, as committed | 2026-11-09 (copy) | recorded |
| `lock_npm_dev.json` | Generated in a scratch directory outside the repo from the `package.json` below; byte copy of the resulting `package-lock.json` | `npm install --package-lock-only --ignore-scripts --cache <scratch>/npm-cache` (resolves against the registry, writes the lockfile only; nothing installed or executed; scratch directory deleted afterwards) | npm 11.12.1, node v26.0.0 | 2026-11-09 | generated |
| `lock_npm_edge.json` | Hand-written; no tool produced it. Package names and versions are real; `resolved` URLs follow the registry pattern; there are no `integrity` hashes (none were fabricated) | none | n/a | 2026-11-09 | synthetic |
| `lock_uv_backend.toml` | `backend/uv.lock` (this repository's own lockfile; frozen byte-identical snapshot) | `cp backend/uv.lock backend/core/graph/tests/fixtures/lock_uv_backend.toml` | uv lockfile `version = 1`, `revision = 3`, as committed | 2026-11-09 (copy) | recorded |
| `lock_poetry.toml` | Generated in a scratch directory outside the repo from the `pyproject.toml` below; byte copy of the resulting `poetry.lock` | `POETRY_CACHE_DIR=<scratch>/poetry-cache POETRY_VIRTUALENVS_CREATE=false POETRY_NO_INTERACTION=1 uvx --from poetry==2.5.1 poetry lock` (resolves and writes the lockfile only; nothing installed; scratch directory deleted afterwards) | Poetry 2.5.1 (newest on PyPI at the time), lock-version 2.1 | 2026-11-09 | generated |
| `lock_uv_edge.toml` | Hand-written; no tool produced it. Package names and versions are real; dependency relations are chosen to exercise scope rules, not copied from each package's real metadata. There are no `sdist` or `wheels` entries and no hashes (none were fabricated) | none | n/a | 2026-11-09 | synthetic |
| `lock_poetry_edge.toml` | Hand-written; no tool produced it. Package names and versions are real. It mixes the Poetry < 2.0 `category` field and the Poetry ≥ 2.0 `groups` field in one file, which no single Poetry release writes. `files` lists are empty and there is no `content-hash` (none were fabricated) | none | n/a | 2026-11-09 | synthetic |
| `requirements.txt` | Hand-written; no tool produced it. Package names and versions are real. It starts with a UTF-8 BOM and uses `\r\n` line endings (keep both; do not let an editor normalise them). The two `--hash=sha256:` values are placeholders (SHA-256 of the empty string and of `foo`), not digests of the named package | none | n/a | 2026-11-09 | synthetic |

### `lock_poetry.toml` details

- SHA-256: `ecbda5ff952045ad8e463bfda9dbb46c004e31ffbd178760949a31f79a3fa4e6`.
- Two `[[package]]` tables: `six` 1.17.0 with `groups = ["main"]` and `iniconfig` 2.3.1 with `groups = ["dev"]`. Neither has dependencies.
- Scope markers present: `groups` only. There is no `category` field and no package without either field (the synthetic `lock_poetry_edge.toml` covers legacy `category` and the neither-field case). This matches DG-SCP-6 (Poetry ≥ 2.0 shape).
- `[metadata]`: `lock-version = "2.1"`, `python-versions = ">=3.10"`, a `content-hash`. The file records no direct dependencies, so `direct_scopes` is empty.
- Contains no local path (DG-NFR-6).
- `pyproject.toml` used:

```toml
[project]
name = "graveyard-poetry-fixture"
version = "0.0.1"
requires-python = ">=3.10"
dependencies = ["six==1.17.0"]

[tool.poetry]
package-mode = false

[tool.poetry.group.dev.dependencies]
iniconfig = "2.3.1"
```

### `lock_uv_backend.toml` details

- Source path: `backend/uv.lock`. Last commit that touched it (`git log -1 --format=%h -- backend/uv.lock`): `0fbf989`. The working tree copy matched `HEAD` when snapshotted.
- SHA-256: `14d0b57a7ef21aed613cfa232646bdd073cc3cd7149bb6a375b7fff8153f7f42`.
- This is a frozen snapshot. Later changes to `backend/uv.lock` (new dependencies, re-locks) must not be copied here; tests assert against the figures below, which `tomllib` recomputes from this file. To refresh it, re-run the `cp`, update this section and the tests together.
- 21 `[[package]]` tables: one project package, `graveyard-backend` (`source = { virtual = "." }`), and 20 others.
- Project package declares `dependencies` = `packageurl-python`, `pyyaml`, and a `[package.dev-dependencies]` table with one group, `dev` = `hypothesis`, `mypy`, `pytest`, `pytest-cov`, `ruff`, `types-pyyaml`.
- Contains no local path (DG-NFR-6).

### `lock_npm_dev.json` details

- `lockfileVersion`: 3.
- Flags present: `dev: true` on `node_modules/is-number`; `optional: true` on `node_modules/uuid`. No `devOptional`, `peer`, `link`, `inBundle` or nested `node_modules` entries (the synthetic edge fixture covers those).
- `packages[""]` has all three groups: `dependencies` (`left-pad`), `devDependencies` (`is-number`), `optionalDependencies` (`uuid`).
- `package.json` used:

```json
{
  "name": "graveyard-npm-fixture",
  "version": "0.0.1",
  "private": true,
  "dependencies": { "left-pad": "1.3.0" },
  "devDependencies": { "is-number": "7.0.0" },
  "optionalDependencies": { "uuid": "3.4.0" }
}
```

### `lock_npm_edge.json` details (synthetic)

`lockfileVersion` 3, 15 entries including the root `""`. It exists only for cases a small real npm project does not produce (DG-SCP-1…5). The parent/child relations are not meant to be a faithful npm layout; only the flags, path keys and root declarations matter. The package-lock `dev`/`devOptional`/`peer`/`link` flags are the only scope inputs.

Root declarations: `dependencies` = `debug`, `left-pad`, `ms`, `string-width-cjs`, `tslib`; `devDependencies` = `chalk`, `tslib`.

| Entry (path key) | Case exercised | Expected result |
|---|---|---|
| `node_modules/picomatch` (`devOptional: true`) | `devOptional` is not `dev` (DG-SCP-1, D12) | `package_scopes` `runtime`; not declared |
| `node_modules/react` (`peer: true`) | `peer` is not `dev` (DG-SCP-1, D12) | `package_scopes` `runtime`; not declared |
| `node_modules/rollup/node_modules/@types/estree` | nested scoped path; name from the segment after the last `node_modules/` (DG-SCP-2) | key `@types/estree@1.0.5`, `runtime`; `node_modules/rollup` is its ordinary parent entry |
| `node_modules/string-width-cjs` (`name: "string-width"`) | alias; key built from `name` (DG-SCP-2, DG-SCP-4) | key `string-width@4.2.3`, `runtime` in both maps; no entry keyed `string-width-cjs` |
| `node_modules/local-lib` (`link: true`) | link entry skipped without a warning (DG-SCP-1) | not in either map, no warning |
| `packages/local-lib` | path without `node_modules/` (workspace member source) skipped without a warning (DG-SCP-1) | not in either map, no warning |
| `node_modules/semver` (`dev: true`) and `node_modules/ora/node_modules/semver` (no flag) | duplicated package: dev copy and runtime copy of `semver@7.5.4`; any runtime copy wins (DG-SCP-3) | `package_scopes` `runtime`; not declared |
| `node_modules/chalk` (no flag), declared only in `devDependencies`, and required by `node_modules/ora` | devDependency that production also requires (DG-SCP-5, D11) | `direct_scopes` `dev`, `package_scopes` `runtime`; **no warning** |
| `node_modules/debug` (`dev: true`), declared in `dependencies` | runtime declaration whose entry says `dev` (DG-SCP-5) | `direct_scopes` `runtime`, `package_scopes` `dev`; **exactly one** `SCOPE_DISAGREEMENT` with subject `debug@4.3.4` |
| `ms` declared in `dependencies`, no `node_modules/ms` entry | declared name with no entry (DG-SCP-4) | **exactly one** `DIRECT_UNRESOLVED` for `ms`; not in either map |
| `node_modules/tslib` (no flag), declared in both `dependencies` and `devDependencies` | name in both groups is `runtime` (DG-SCP-4) | `direct_scopes` `runtime`, `package_scopes` `runtime`, no warning |
| `node_modules/left-pad`, `node_modules/ora`, `node_modules/rollup` | plain runtime entries | `package_scopes` `runtime` (`left-pad` is also declared `runtime`) |

Whole-file expectation: `package_scopes` has 11 keys (`chalk@4.1.2`, `debug@4.3.4`, `left-pad@1.3.0`, `ora@5.4.1`, `picomatch@2.3.1`, `react@18.2.0`, `rollup@4.9.6`, `semver@7.5.4`, `string-width@4.2.3`, `tslib@2.6.2`, `@types/estree@1.0.5`), all `runtime` except `debug@4.3.4`. `direct_scopes` has 5 keys: `chalk@4.1.2` `dev`; `debug@4.3.4`, `left-pad@1.3.0`, `string-width@4.2.3`, `tslib@2.6.2` `runtime`. Warnings: one `SCOPE_DISAGREEMENT`, one `DIRECT_UNRESOLVED`, nothing else. The v1-shaped rejection document is built inline in the test, not stored here.

### `lock_uv_edge.toml` details (synthetic)

`version = 1`, `revision = 3`, 14 `[[package]]` tables: one project package, `edge-fixture` (`source = { virtual = "." }`), and 13 others. It exists only for cases a small real uv project does not produce (DG-SCP-7, DG-SCP-5, DG-EX-21). Only `name`, `version`, `source`, `dependencies`, `optional-dependencies` and `dev-dependencies` are present; `typing-extensions` references carry `version` because uv writes it when a name has several versions. Keys below are `pypi_key(name, version)`, written `pypi/<name>@<version>`.

Project package: `dependencies` = `requests`, `tomli`; `[package.optional-dependencies]` `yaml` = `pyyaml`; `[package.dev-dependencies]` `dev` = `httpx`, `pytest`.

Edges between the other packages: `requests` → `certifi`, `charset-normalizer`, `idna`, `urllib3`, and its optional group `socks` → `pysocks`; `httpx` → `certifi`, `idna`; `pytest` → `pluggy`, `typing-extensions` 4.10.0; `pluggy` optional group `testing` → `pytest`; `urllib3` → `typing-extensions` 4.12.2. `pyyaml`, `pysocks`, `six`, `certifi`, `charset-normalizer`, `idna` and both `typing-extensions` have no dependencies.

| Entry | Case exercised | Expected result |
|---|---|---|
| `certifi@2024.8.30`, `idna@3.10` | reachable from a runtime seed (`requests`) and from a dev seed (`httpx`) (DG-SCP-7) | `package_scopes` `runtime`; not declared |
| `pysocks@1.7.1` | target of another package's `optional-dependencies` (`requests` group `socks`); optional edges are followed (DG-SCP-7) | `package_scopes` `runtime`; not declared |
| `pyyaml@6.0.2` | target of the project's own `optional-dependencies` (DG-SCP-7) | `package_scopes` `runtime`; `direct_scopes` `runtime` |
| `pytest@8.3.3` ↔ `pluggy@1.5.0` | cycle among dev packages (`pytest` → `pluggy` via `dependencies`, `pluggy` → `pytest` via `optional-dependencies`); closure terminates (DG-SCP-7) | both `dev`; `pytest` is also declared `dev`; no hang, no warning |
| `typing-extensions@4.10.0` and `typing-extensions@4.12.2` | one name with two versions; each reference carries a `version` and narrows to one entry (DG-SCP-7) | `4.12.2` `runtime` (via `urllib3`); `4.10.0` `dev` (via `pytest`); neither declared |
| `tomli` in the project's `dependencies` | reference that resolves to nothing: no `[[package]]` named `tomli` (DG-SCP-7) | **exactly one** `DIRECT_UNRESOLVED`, subject `tomli`; not in either map |
| `six@1.16.0` | reachable from no seed (DG-SCP-7, D8) | `package_scopes` `runtime`; not declared |
| `edge-fixture` | project package (DG-SCP-7) | absent from both maps |
| `requests@2.32.3`, `charset-normalizer@3.4.0`, `urllib3@2.2.3` | plain runtime closure | `package_scopes` `runtime`; only `requests` is declared (`runtime`) |
| `httpx@0.27.2` | plain dev seed | `package_scopes` `dev`; `direct_scopes` `dev` |

Whole-file expectation:

- `package_scopes` has 13 keys. `dev` (4): `httpx@0.27.2`, `pluggy@1.5.0`, `pytest@8.3.3`, `typing-extensions@4.10.0`. `runtime` (9): `certifi@2024.8.30`, `charset-normalizer@3.4.0`, `idna@3.10`, `pysocks@1.7.1`, `pyyaml@6.0.2`, `requests@2.32.3`, `six@1.16.0`, `typing-extensions@4.12.2`, `urllib3@2.2.3`.
- `direct_scopes` has 4 keys: `requests@2.32.3` and `pyyaml@6.0.2` `runtime`; `httpx@0.27.2` and `pytest@8.3.3` `dev`.
- Warnings: one `DIRECT_UNRESOLVED` (subject `tomli`; the design gives no subject format for uv, so T5.5 and T5.6 should agree on the referenced name, as `parse_package_lock` does), nothing else. In particular no `SCOPE_DISAGREEMENT` (DG-SCP-5: it cannot fire for `uv.lock`).

### `lock_poetry_edge.toml` details (synthetic)

Six `[[package]]` tables, a `[metadata]` table with `lock-version = "2.1"` and `python-versions`. It exists only for scope-field shapes a single real Poetry release does not write together (DG-SCP-6, DG-EX-20). No package has dependencies; `direct_scopes` is always empty. Keys are `pypi_key(name, version)`, written `pypi/<name>@<version>`.

| Entry | Case exercised | Expected result |
|---|---|---|
| `requests` 2.31.0 (`category = "main"`, no `groups`) | legacy Poetry < 2.0 main (DG-SCP-6) | `runtime` |
| `pytest` 7.4.4 (`category = "dev"`, no `groups`) | legacy Poetry < 2.0 dev (DG-SCP-6) | `dev` |
| `certifi` 2023.11.17 (`groups = ["main", "dev"]`) | `"main"` among several groups (DG-SCP-6) | `runtime` |
| `coverage` 7.4.0 (`groups = ["dev", "test"]`) | several groups, none `"main"` (DG-SCP-6) | `dev` |
| `idna` 3.6 (neither `groups` nor `category`) | no scope field (DG-SCP-6, D8) | `runtime` |
| `Flask_SQLAlchemy` 3.1.1 (`groups = ["main"]`) | mixed-case name with an underscore; key built from the normalised name (DG-SCP-6, DG-EX-20) | key `pypi/flask-sqlalchemy@3.1.1`, `runtime`; no key with `Flask_SQLAlchemy` |

Whole-file expectation: `package_scopes` has 6 keys. `runtime` (4): `pypi/certifi@2023.11.17`, `pypi/flask-sqlalchemy@3.1.1`, `pypi/idna@3.6`, `pypi/requests@2.31.0`. `dev` (2): `pypi/coverage@7.4.0`, `pypi/pytest@7.4.4`. `direct_scopes` is empty. No warnings.

### `requirements.txt` details (synthetic)

Covers every DG-EX-22 form (DG-SCP-8). Keys are `pypi_key(name, version)`, written `pypi/<name>@<version>`.

| Line | Case exercised | Expected result |
|---|---|---|
| leading BOM (first line is the `#` header comment) | BOM accepted | no effect |
| `-r other.txt`, `-e .`, `# …` header, blank line | skipped silently | no entry, no warning |
| `requests==2.31.0` | plain pin | `runtime` |
| `flask[async]==3.0.0` | extras | `pypi/flask@3.0.0` |
| `numpy == 1.26.4 ; python_version < "3.9"` | spaces around operator, environment marker | `pypi/numpy@1.26.4` |
| `urllib3==2.2.1  # trailing comment` | trailing comment | `pypi/urllib3@2.2.1` |
| `six===1.16.0` | arbitrary-equality pin | `pypi/six@1.16.0` |
| `certifi==2024.2.2 \` + two `--hash=` lines | `\` continuation with hashes | `pypi/certifi@2024.2.2` |
| `git+https://github.com/psf/requests.git@main#egg=requests` | URL requirement | `REQUIREMENT_SKIPPED` |
| `requests>=2` | range | `REQUIREMENT_SKIPPED` |
| `flask==1.*` | wildcard pin | `REQUIREMENT_SKIPPED` |
| `./local` | relative path placeholder (not a real path on any machine) | `REQUIREMENT_SKIPPED` |

Whole-file expectation: `package_scopes` equals `direct_scopes`, 6 keys, all `runtime` (`certifi`, `flask`, `numpy`, `requests`, `six`, `urllib3`). Exactly 4 warnings, all `REQUIREMENT_SKIPPED`, with subjects `git+https://…`, `requests>=2`, `flask==1.*`, `./local`.

Measured figures for `syft_npm.cdx.json` are in `docs/SPIKES.md` ("Q5 addendum, re-recorded 9 Nov 2026") and are re-computed from the file by `test_fixtures.py`.
