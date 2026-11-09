# Fixtures for `core/graph`

Paths in the **Command** column are relative to the repo root. No fixture contains a local path (DG-NFR-6). Syft only reads files; nothing was installed or executed to produce these.

| File | Source | Command | Tool version | Date | Kind |
|---|---|---|---|---|---|
| `syft_npm.cdx.json` | `spikes/fixtures/npm` (lockfile with `JSONStream`, 116 entries); identical to `spikes/npm-sbom.cdx.json` | `SYFT_CHECK_FOR_APP_UPDATE=false ~/.local/bin/syft dir:spikes/fixtures/npm -o cyclonedx-json=spikes/npm-sbom.cdx.json`, then one exact-string edit: `metadata.component.name` `spikes/fixtures/npm` → `fixtures/npm` | Syft 1.56.0 | 2026-11-09 | recorded |
| `syft_py.cdx.json` | `spikes/py-sbom.cdx.json` (recorded 2026-11-03 from `spikes/fixtures/py`) | one exact-string edit: `metadata.component.name` the author's absolute path to `spikes/fixtures/py` → `fixtures/py` | Syft 1.56.0 | 2026-11-09 (copy) | recorded |
| `lock_npm.json` | `spikes/fixtures/npm/package-lock.json` (byte copy) | `cp` | npm lockfile, as committed | 2026-11-09 (copy) | recorded |
| `lock_uv.toml` | `spikes/fixtures/py/uv.lock` (byte copy) | `cp` | uv lockfile, as committed | 2026-11-09 (copy) | recorded |

Measured figures for `syft_npm.cdx.json` are in `docs/SPIKES.md` ("Q5 addendum, re-recorded 9 Nov 2026") and are re-computed from the file by `test_fixtures.py`.
