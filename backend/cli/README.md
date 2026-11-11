# graveyard CLI

`graveyard autopsy` runs the whole Graveyard pipeline on your machine: it finds the dependencies of a project (or of the packages you name), looks each one up in the public sources, scores it with the deterministic mortality model, ranks the results by priority, prints a table and can write a versioned JSON report. It exits with a code a CI job can gate on.

The CLI is glue. It holds no scoring rules (`core.scoring` does), parses no responses (`core.sources` does) and opens no sockets of its own (`sources` does, against a fixed list of hosts). It never executes or installs anything from the project it reads.

## Two modes

**Project mode** takes a directory.

```
graveyard autopsy PATH [--sbom FILE] [options]
```

Every directory under `PATH` that directly contains a lockfile (`package-lock.json`, `uv.lock`, `poetry.lock` or `requirements*.txt`) is a *service*. Syft 1.56.0 produces one CycloneDX document per service (or `--sbom FILE` supplies one document for the whole project), the lockfiles supply the runtime or dev scope of each package, and the dependency graph gives each package its exposure.

**Single-package mode** takes package URLs and skips discovery, Syft and the graph. It is meant for an install-time check.

```
graveyard autopsy --purl pkg:npm/request@2.88.2 [--purl ...] [options]
```

Each purl must be an npm or PyPI package URL with a version. There is no graph, so exposure is assumed to be the highest weight.

`PATH`, `--sbom` and `--purl` combine in exactly two ways: `PATH` with an optional `--sbom`, or one or more `--purl`. Anything else is a usage error.

## Install and run

From `backend/`:

```
uv run graveyard autopsy PATH
uv run python -m cli autopsy PATH
```

Project mode needs Syft **1.56.0** (exactly). The CLI does not install or update it. Install that release from the Syft releases page, then either put it on `PATH` or pass `--syft PATH`. `--sbom FILE` avoids Syft altogether.

## Options

| Option | Meaning |
|---|---|
| `PATH` | Project directory (project mode). |
| `--purl PURL` | Package URL with a version; repeatable; replaces `PATH`. |
| `--sbom FILE` | Use this CycloneDX 1.5 to 1.7 JSON document instead of running Syft. One service, `"."`. Scopes come from lockfiles directly in `PATH` (not recursive). |
| `--json FILE` | Write the JSON report here (also when the gate trips). |
| `--fail-on LIST` | Comma-separated classes, case-insensitive: `dead`, `cursed`, `ailing`. Exit 1 if any package is in any named class. |
| `--as-of YYYY-MM-DD` | Score as of this date (default: today, UTC). Not in the future. |
| `--all` | List every package in the table (default: only those that need attention). The JSON always lists every package. |
| `--syft PATH` | Syft executable (default: `syft` on `PATH`). Ignored in `--purl` mode. |
| `--syft-timeout SECONDS` | Timeout for each Syft run, default 120. Ignored in `--purl` mode. |
| `--version` | Print the version and exit. |
| `--help` | Print help, including the exit-code table, and exit. |

There is no option that takes a token or any other secret.

## Environment

The environment is read in one place, `cli/__main__.py`, and nowhere else.

| Variable | Use |
|---|---|
| `GITHUB_TOKEN` | Optional. Sent only to `api.github.com`, for repository signals (archived flag, last push, committers, issue counts). Only public data is read, so a token with no extra scopes or permissions is expected to be enough. An empty or whitespace-only value counts as no token. A value that is not a valid token (inner whitespace, control characters, over 255 characters) is ignored with a warning. The value is never printed, logged or written to the report, and is never passed to Syft. |
| `GRAVEYARD_CONTACT` | Optional contact for the `User-Agent` sent to the public APIs. Default: `https://github.com/olajaido/graveyard`. |

**Without a token the run still works.** GitHub signals are missing, confidence is lower, the report says `degraded: true`, and stderr carries one `no GITHUB_TOKEN set` warning. The exit code is not changed by that. When you use `--fail-on` on a degraded run, stderr also says the gate was evaluated on partial evidence and how many packages are Unknown, because a package with little evidence may not reach Dead or Ailing.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | the run completed and the gate did not trip |
| 1 | the run completed and the gate tripped |
| 2 | usage error |
| 3 | input or tool error |
| 4 | internal error |

- **0** includes degraded runs and runs where some inputs were skipped as item errors.
- **1** means at least one ranked package is in a class named by `--fail-on`. Without `--fail-on` the gate never trips.
- **2**: unknown option, bad `--fail-on` or `--as-of`, a missing directory, `PATH` with `--purl`, `--sbom` with `--purl`, an invalid or version-less `--purl`.
- **3**: no lockfiles under `PATH` (use `--sbom`), more than 50 services, Syft missing, the wrong version, failed, timed out or producing bad output, an unreadable or invalid SBOM, or a failure to write `--json`. A failure for any one service is fatal, so a gate cannot pass on a service that was not scanned.
- **4**: a bug. The message names the exception type and nothing else.

The JSON report is written only for a completed analysis (codes 0 and 1).

## `--fail-on`

The list is a set, not a threshold: a package matches if it is in *any* named class. `dead` is base state Dead, `ailing` is base state Ailing (it does not include Dead), and `cursed` is the Cursed overlay (a known vulnerability with no fixed version), whatever the base state. Unknown packages never match. To gate on everything pass `dead,cursed,ailing`.

## The table

| Column | Content |
|---|---|
| `STATE` | `Dead`, `Ailing`, `Resting`, `Alive` or `Unknown`, followed by ` · Cursed` or ` · Wounded` for the overlay (Cursed wins when both apply). |
| `PACKAGE` | `<ecosystem> <name>@<version>`. |
| `WHY` | A short reason built from the score and the evidence: `declared dead`, the largest contributions (`last release 2014-06`, `Scorecard maintained 0/10`, ...), `N advisories with no fix`, `fix available`, `upgrade advised`. |
| `EXPOSURE` | `direct` or `transitive`, then `runtime` or `dev`, plus ` · N services` when several; `assumed` when there is no graph. |
| `PRIORITY` | The ranking number, one decimal place (`—` for Unknown). Rows are ordered by it, highest first. |

A footer line gives the counts per state and how many rows were hidden. Everything printed is passed through a filter that replaces control characters and bidirectional overrides, so a hostile package name cannot inject a terminal escape sequence.

## JSON report, schema `graveyard.autopsy` version 1

Top-level keys, in order: `schema`, `schema_version`, `model_version`, `as_of`, `input`, `summary`, `packages`, `errors`, `warnings`.

- `input`: `mode` (`syft`, `sbom` or `purl`), `syft_version`, `services`, `lockfiles` (`service`, `file`, `used`).
- `summary`: package count, `states` (all five keys), `cursed`, `wounded`, `item_errors`, `degraded`, warning counts, source statistics, `gate` (`fail_on`, `tripped`, `matches`) and `exit_code`.
- `packages`: every scored package in rank order, with `rank`, `purl`, `key`, `ecosystem`, `name`, `version`, `state`, `dead_reason`, `cursed`, `wounded`, `mortality`, `confidence`, `priority`, `exposure`, `exposure_assumed`, `services_affected`, `direct`, `scope`, `manifests`, `path_infos`, `example_paths`, `why`, `normalised_risks`, `contributions`, `evidence`, `repo`, `repo_via`, `resolved_version`, `latest_version` and `warnings`. Numbers are unrounded.
- `evidence`: the 11 signals, each with `value`, `source_url`, `fetched_at`, `extra_source_urls` and `note`, so every point of the score can be traced to a link.
- `errors`: inputs the sources rejected (`purl`, `code`, `detail`); they are not ranked and do not change the exit code.
- `warnings`: graph warnings (`origin: "graph"`) and CLI warnings (`origin: "cli"`). Source warnings are under each package.

**Nullability by mode.** In `--purl` mode `services_affected`, `direct` and `scope` are `null` and `manifests`, `path_infos` and `example_paths` are empty arrays. `model_version` is `null` only when no package was scored. The file contains no absolute path, no environment value and no token. For identical inputs, date and source answers the file is byte-identical.

**Versioning rule.** Adding a key keeps `schema_version` at 1. Renaming, removing or retyping a key, or changing what a value means, requires version 2 and a migration note here. `tests/fixtures/report_v1_shape.json` records the shape and a test fails on any drift.

## Use from a hook

The install-time hook asks one question per package: is it dead or cursed?

```
graveyard autopsy --purl <purl> --fail-on dead,cursed
```

That command exits 1 when the package matches. **Do not wire it straight into a Kiro PreToolUse hook.** The Kiro documentation is not consistent about which non-zero exit codes block a Pre Tool Use hook: [Hook actions](https://kiro.dev/docs/hooks/actions/) says any non-zero exit blocks and sends stderr to the agent, while [Hook types](https://kiro.dev/docs/hooks/types/) gives no exit-code table for Pre Tool Use, and third-party Kiro CLI notes say only exit 2 blocks. Use a small wrapper that fails open and blocks only when sure:

| CLI exit | Wrapper exit | Wrapper output |
|---|---|---|
| 0 | 0 | none |
| 1 (gate tripped) | 2 | the reason on stderr |
| 2, 3 or 4 | 0 | one line on stdout: `graveyard could not check <purl>: <reason>` |

The wrapper never exits 1. The wrapper itself belongs to the `kiro-power` spec.

## Known limitations

- `requirements*.txt` files are treated as runtime, including `requirements-dev.txt`, so the exposure of dev-only requirements is overstated.
- Syft may catalogue more than the lockfiles list. Packages without lockfile data get `runtime` scope and a `SCOPE_ASSUMED` warning.
- The cache lives in memory for one run; there is no persistent cache.
- Syft runs once per service, one after another, with each nested service excluded from its parent. A directory name containing `* ? [ ] { }` is rejected because it would be misread as a glob.
- `pnpm-lock.yaml`, `yarn.lock` and `Pipfile.lock` are not read for scopes yet.
- `--purl` runs the full lookup for each package. That is several HTTP requests per package, and with no token the GitHub signals are missing.
- Data is public and only npm and PyPI are covered.

## Manual smoke test with the real Syft

CI has no Syft and the run uses the network, so this is run by hand. It needs Syft 1.56.0:

```
SYFT_CHECK_FOR_APP_UPDATE=false uv run graveyard autopsy cli/tests/fixtures/anchors-project \
  --syft ~/.local/bin/syft --as-of 2026-11-03 --all
```

Run it without `GITHUB_TOKEN` to see the degraded path. The expected result is the nine anchor packages, with request, left-pad, node-uuid, nose and pycrypto Dead. Live data may differ in detail from the recorded cassette the tests use.
