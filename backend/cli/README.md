# graveyard CLI

`graveyard autopsy` runs the whole Graveyard pipeline on your machine: it finds the dependencies of a project (or of the packages you name), looks each one up in the public sources, scores it with the deterministic mortality model, ranks the results by priority, prints a table and can write a versioned JSON report. It exits with a code a CI job can gate on.

The CLI is glue. It holds no scoring rules (`core.scoring` does), parses no responses (`core.sources` does) and opens no sockets of its own (`sources` does, against a fixed list of hosts). It never executes or installs anything from the project it reads.

## Two modes

**Project mode** takes a directory.

```
graveyard autopsy PATH [--sbom FILE] [options]
```

Every directory under `PATH` that directly contains a lockfile (`package-lock.json`, `uv.lock`, `poetry.lock` or `requirements*.txt`) is a *service*. Syft 1.56.0 produces one CycloneDX document per service (or `--sbom FILE` supplies one document for the whole project), the lockfiles supply the runtime or dev scope of each package and the project's declared direct dependencies, and the dependency graph gives each package its exposure. See "Dev dependencies and direct edges" below for what the CLI adds to Syft's output.

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

Project mode needs Syft **1.56.0** (exactly). The CLI does not install or update it. It starts Syft with a cleared environment plus `SYFT_CHECK_FOR_APP_UPDATE=false` and `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true`, and no other `SYFT_*` setting reaches it. Install that release from the Syft releases page, then either put it on `PATH` or pass `--syft PATH`. `--sbom FILE` avoids Syft altogether.

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

**Without a token the run still works.** GitHub signals are missing, confidence is lower, the report says `degraded: true`, and stderr carries one `no GITHUB_TOKEN set` warning. The exit code is not changed by that. When you use `--fail-on` on a degraded run, stderr also says the gate was evaluated on partial evidence and, when there are any, how many packages are Unknown. A package that is Dead only because its remaining signals scored badly while GitHub data was skipped is shown as *unverified* and is not gated (see "`--fail-on`").

## Exit codes

| Code | Meaning |
|---|---|
| 0 | the run completed and the gate did not trip |
| 1 | the run completed and the gate tripped |
| 2 | usage error |
| 3 | input or tool error |
| 4 | internal error |

- **0** includes degraded runs and runs where some inputs were skipped as item errors.
- **1** means at least one ranked, gate-eligible package is in a class named by `--fail-on`. Without `--fail-on` the gate never trips.
- **2**: unknown option, bad `--fail-on` or `--as-of`, a missing directory, `PATH` with `--purl`, `--sbom` with `--purl`, an invalid or version-less `--purl`.
- **3**: no lockfiles under `PATH` (use `--sbom`), more than 50 services, Syft missing, the wrong version, failed, timed out or producing bad output, an unreadable or invalid SBOM, or a failure to write `--json`. A failure for any one service is fatal, so a gate cannot pass on a service that was not scanned.
- **4**: a bug. The message names the exception type and nothing else.

The JSON report is written only for a completed analysis (codes 0 and 1).

## `--fail-on`

The list is a set, not a threshold: a package matches if it is in *any* named class. `dead` is base state Dead, `ailing` is base state Ailing (it does not include Dead), and `cursed` is the Cursed overlay (a known vulnerability with no fixed version), whatever the base state. Unknown packages never match. To gate on everything pass `dead,cursed,ailing`.

**Only evidence that was seen is gated.** A package is *gate-eligible* unless its verdict rests on the score **and** at least one of its scored signals is missing because a source was skipped or failed: no `GITHUB_TOKEN`, a rate limit, a network error, a malformed response. A verdict rests on the score when the package is Dead *by score* (not declared dead) or Ailing, and is not Cursed through the age rule. Such a package is *unverified*: it keeps its state and priority in the table, its `WHY` starts with `unverified: no <source> data` (for example `unverified: no GitHub data`), and `--fail-on` ignores it, whatever class it names (`dead` or `ailing`). A signal that is missing because the data does not exist (no repository could be resolved, a 404) does not count, because nothing was skipped. Declared Dead is always gated. Cursed is gated when a no-fix advisory is old enough on its own (the model's age rule); a package that is Cursed only because it is Dead or Ailing (the model counts any no-fix advisory then) follows the verdict it is Cursed on. The sources say which case applies: the warnings of a package list exactly the signals that its failures left missing. The table footer counts unverified packages (`N unverified, not gated; set GITHUB_TOKEN to verify`), stderr says how many were not gated, and the JSON has `gate_eligible` and `unverified_reason` for every package.

## Dev dependencies and direct edges

Syft 1.56.0 does two things that the dependency graph cannot use as it is (`docs/SPIKES.md`, Q7): it leaves out the `dev: true` packages of a `package-lock.json` unless it is told otherwise, and it never links a project's root to its dev direct dependencies (npm `devDependencies`, uv dev groups). The CLI therefore:

1. starts Syft with `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true`, and
2. adds `root -> direct` edges for every direct dependency the lockfile declares and the root does not already reach (`cli/augment.py`), before the graph is built. Only root-sourced edges are added; nothing is removed or changed.

Without the second step an orphan dev package that has edges of its own would be read as a second *root* and dropped, and one without edges would be unreachable (its exposure assumed). The number of edges added is `summary.stats.direct_edges_added` in the JSON; added edges are not warnings. A declared direct dependency that has no component in the SBOM at all produces one `DIRECT_NOT_IN_SBOM` warning per service, with the keys as `subjects`; those packages are not analysed. This runs in project mode and in `--sbom` mode when lockfiles sit directly in `PATH`.

The root is the one unreferenced `dependencies` entry whose package is not itself a declared direct dependency, or `metadata.component` when a project has only dev dependencies. If the root cannot be told, nothing is added and the graph warns `MULTIPLE_ROOTS` or `ROOT_NOT_FOUND`.

## The table

| Column | Content |
|---|---|
| `STATE` | `Dead`, `Ailing`, `Resting`, `Alive` or `Unknown`, followed by ` · Cursed` or ` · Wounded` for the overlay (Cursed wins when both apply). |
| `PACKAGE` | `<ecosystem> <name>@<version>`. |
| `WHY` | A short reason built from the score and the evidence: `declared dead`, the largest contributions (`last release 2014-06`, `Scorecard maintained 0/10`, ...), `N advisories with no fix`, `fix available`, `upgrade advised`. |
| `EXPOSURE` | `direct` or `transitive`, then `runtime` or `dev`, plus ` · N services` when several; `assumed` when there is no graph. |
| `PRIORITY` | The ranking number, one decimal place (`—` for Unknown). Rows are ordered by it, highest first. |

A footer line gives the counts per state and how many rows were hidden, followed by a line for unverified packages when there are any. `WHY` is the first column to be shortened when the terminal is narrow (the width comes from the terminal, 100 when it is not one); the unverified text is kept short (`unverified: no GitHub data`) so that it fits 100 columns. The JSON `unverified_reason` keeps the long form (`github data unavailable`). Everything printed is passed through a filter that replaces control characters and bidirectional overrides, so a hostile package name cannot inject a terminal escape sequence.

## JSON report, schema `graveyard.autopsy` version 1

Top-level keys, in order: `schema`, `schema_version`, `model_version`, `as_of`, `input`, `summary`, `packages`, `errors`, `warnings`.

- `input`: `mode` (`syft`, `sbom` or `purl`), `syft_version`, `services`, `lockfiles` (`service`, `file`, `used`).
- `summary`: package count, `states` (all five keys), `cursed`, `wounded`, `item_errors`, `degraded`, warning counts, source statistics (`sources`), `stats` (`direct_edges_added`, `unverified`), `gate` (`fail_on`, `tripped`, `matches`, which lists gate-eligible packages only) and `exit_code`.
- `packages`: every scored package in rank order, with `rank`, `purl`, `key`, `ecosystem`, `name`, `version`, `state`, `dead_reason`, `cursed`, `wounded`, `mortality`, `confidence`, `priority`, `exposure`, `exposure_assumed`, `services_affected`, `direct`, `scope`, `manifests`, `path_infos`, `example_paths`, `why`, `gate_eligible`, `unverified_reason`, `normalised_risks`, `contributions`, `evidence`, `repo`, `repo_via`, `resolved_version`, `latest_version` and `warnings`. Numbers are unrounded.
- `evidence`: the 11 signals, each with `value`, `source_url`, `fetched_at`, `extra_source_urls` and `note`, so every point of the score can be traced to a link.
- `errors`: inputs the sources rejected (`purl`, `code`, `detail`); they are not ranked and do not change the exit code.
- `warnings`: graph warnings (`origin: "graph"`) and CLI warnings (`origin: "cli"`: `LOCKFILE_UNREADABLE`, `GITHUB_TOKEN_MISSING`, `GITHUB_TOKEN_INVALID`, `DIRECT_NOT_IN_SBOM`). Source warnings are under each package.

**Nullability by mode.** In `--purl` mode `services_affected`, `direct` and `scope` are `null` and `manifests`, `path_infos` and `example_paths` are empty arrays. `model_version` is `null` only when no package was scored. The file contains no absolute path, no environment value and no token. For identical inputs, date and source answers the file is byte-identical.

**Versioning rule.** Adding a key keeps `schema_version` at 1. Renaming, removing or retyping a key, or changing what a value means, requires version 2 and a migration note here. `tests/fixtures/report_v1_shape.json` records the shape and a test fails on any drift.

## `check-install`

`graveyard check-install` is the command behind the Kiro PreToolUse hook. It reads a hook payload on stdin (or takes the shell command as one `COMMAND` argument), finds the packages an `npm`, `pnpm`, `yarn`, `pip`, `uv` or `poetry` install command would add, checks each one with the same pipeline as `autopsy --purl`, and answers with an exit code the hook can use directly. It runs nothing from the command it reads: the command text is only tokenised.

```
graveyard check-install [COMMAND] [--budget SECONDS] [--as-of YYYY-MM-DD]
echo '{"tool_input":{"command":"npm install request"}}' | graveyard check-install
```

`--budget` is the time limit for the whole check, 0.5 to 60 seconds (default 10). `--as-of` scores as of a date and is meant for tests. At most 20 distinct packages are checked per command; the note says when the rest were not.

**Exit codes of the hook.** The hook returns only two codes. The table is generated from `HookExit` in `cli/hook.py`, is the one `graveyard --help` prints, and a test keeps this README in step with it.

| Code | Meaning |
|---|---|
| 0 | allow: nothing to check, nothing to block, or the check could not finish |
| 2 | block: a dead or cursed package is in the install command |

**It fails open.** Every failure, including an unreadable payload, a timeout, an unresolvable package, unavailable sources and an internal error, exits 0, with at most one line on stdout saying what was not checked. It never exits 1, 3 or 4. Exit 2 is returned only when a gate-eligible package is known to be dead or cursed (the `--fail-on dead,cursed` gate of `autopsy`, reused). An agent cannot tell a failed check from a safe package, so a block means "known dead" and an allow is no guarantee of "healthy". The hook is a guard rail, not a gate. A block writes the reason to stderr and nothing to stdout.

**The range rule.** A package pinned to an exact version is judged on that version. A package with no version, `latest`, `*` or a lone `>=V` is judged on the latest version, because that is what the manager installs. For any other range (`^1.2`, `~=2.0`, `<3`), the installed version may differ from the latest, so only a package that is *declared* Dead (deprecated or archived by its maintainers) may block. A range target that is Cursed, or Dead only by score, never blocks; it appears in the note as `range not checked against <range>`.

**`-r` requirements files.** For `pip install -r FILE`, `python -m pip install -r`, `uv pip install -r` and `uv add -r` (also `--requirement`), the pinned lines of the file are checked as exact versions. No other manager reads a file. `cli/requirements_file.py` is the only module that reads one.

- **Confinement.** The base directory is the payload's `cwd` when it is an absolute path to an existing directory, otherwise the process working directory. A relative path is joined to the base; an absolute path must resolve inside it. Symlinks are followed and the result must still be inside the base and be a regular file. Paths containing `~`, `$`, a glob character or `://` are refused. A directory or a FIFO is never opened.
- **Caps.** At most 5 files per command, at most 1 MiB per file (never read past the cap), and the file targets share the 20-package limit, after the targets on the command line, de-duplicated.
- **Skipped lines are counted, not shown.** Nested `-r` and `-c` lines are not followed. URL or path lines and lines not pinned with `==` are skipped. The note reports `<file>: N lines not checked (unpinned, URL or path, nested -r)`, or `<file>: not read (<reason>)` when the file could not be read. No line of a file is ever printed.

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

- If a service's lockfile cannot be read there is nothing to add edges from, so the dev-package problem above returns for that service: the run completes, warns `LOCKFILE_UNREADABLE`, and the graph reports `MULTIPLE_ROOTS` (an orphan dev package with edges of its own is read as a second root and left out of the packages).
- The root of a project cannot be found when several unexplained orphan roots exist, or when there is neither a root entry nor a `metadata.component`; nothing is added then. Packages that are unreachable but not declared in the lockfile (for example a transitive dev dependency whose parent Syft left out) stay unreachable and have assumed exposure.
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

Run it without `GITHUB_TOKEN` to see the degraded path (`six` is then Dead on partial evidence, shown as unverified and not gated, as would an Ailing verdict reached the same way). The expected result is the nine anchor packages, with request, left-pad, node-uuid, nose and pycrypto Dead. Live data may differ in detail from the recorded cassette the tests use.

The same check exists as an opt-in contract test, marked `syft`, which runs the real binary on the fixture project and asserts the nine packages and their paths after augmentation. It skips itself, with a reason, unless a `syft` reporting exactly 1.56.0 is found on `PATH` or in `~/.local/bin`:

```
uv run pytest -m syft -q cli      # only the contract tests
uv run pytest -m "not syft" -q    # everything else
```
