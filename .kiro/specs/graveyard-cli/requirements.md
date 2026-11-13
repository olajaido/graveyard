# Spec: graveyard-cli

> **Source of truth:** PRD §7.3–7.5 (score, state classification, priority), §8.1 EX-2, EX-4, EX-6, EX-8, EX-9 (ingest, scopes, services), §8.2 AU-2, AU-3, AU-4 (autopsy, evidence, degradation), §13 T6 and T9 (secrets, never execute user code), the hook table row H6 (`--fail-on dead,cursed`); `docs/SPIKES.md` Q5 and its 9 Nov addendum (Syft 1.56.0, CycloneDX output, root detection); `docs/adr/0001-data-sources-and-sbom.md` decisions 1–2; steering `tech.md`, `security.md`, `structure.md`, `testing.md`, `mortality-model.md`.
> **Public APIs consumed (from the four completed specs, unchanged):**
> - `core.graph`: `build_graph`, `ServiceInput`, `ScopeResult`, `parse_package_lock`, `parse_uv_lock`, `parse_poetry_lock`, `parse_requirements_txt`, `exposure_inputs`, `graph_to_dict`, `DependencyGraph`, `GraphNode`, `GraphWarning`.
> - `core.purl`: `parse_purl`, `registry_name` (display of name and version only).
> - `sources` and `core.sources`: `SourceSession`, `MemoryCache`, `SystemClock`, `SourcesConfig.default(contact=…)`, `SecretToken`, `SourceResult`, `Evidence`, `SourceWarning`, `BatchResult`.
> - `core.scoring`: `score_package`, `sort_results`, `ScoringResult`, `BaseState`.
>
> **Scope:** the walking skeleton that runs the whole pipeline on a developer's machine, in two modes of one command:
> - **Project mode:** `graveyard autopsy <path>` finds lockfiles, produces one SBOM per manifest directory with Syft 1.56.0 (or reads `--sbom`), builds the graph, autopsies every node, scores it, ranks by priority, prints a table and optionally writes a versioned JSON report, and exits with a code a CI job can gate on.
> - **Single-package mode:** `graveyard autopsy --purl <purl> [--purl …]` autopsies the given packages with no discovery, Syft or graph, for the dead-install-blocker hook (H9). Same table, JSON, `--fail-on` and exit codes.
>
> Code is in `backend/cli/`. The one change outside it is the packaging in `pyproject.toml` (D2).
>
> **Out of scope (belongs elsewhere, see "Belongs elsewhere" below):** the `check-install` (command-line parsing for the hook) and `scan` subcommands; the Lambda/Step Functions path; persistent caches; Bedrock narration; themed or coloured output; rites; the GitHub Action; metrics emission; any change to `core.*` or `sources`.

---

## Design decisions recorded by this spec

| ID | Decision | Rationale and consequence |
|----|----------|---------------------------|
| D1 | **One subcommand, `autopsy`, with two input modes** (path or `--purl`). It replaces the `check` of the PRD: PRD §14, `structure.md` and hook H6 must be updated to the name `autopsy` (listed under "Belongs elsewhere"). `check-install` and `scan` stay later specs that reuse this pipeline. | Decided in review (Q4). One command keeps one table, one JSON schema and one exit-code table for the CI gate and the install hook. |
| D2 | **Entry point `graveyard`** is a console script, `graveyard = "cli.__main__:main"`; `python -m cli` is the same code. Packaging: a pinned `hatchling` build backend, `[tool.uv] package = true`, wheel packages `core`, `sources`, `cli`, and package data (`core/scoring/weights.v1.yaml`) included; tests and fixtures excluded from the wheel. `uv run` keeps working (editable install by `uv sync`). | Decided in review (Q1). `package = false` installs no scripts. The change touches how the backend is installed, so the Lambda impact is recorded under "Belongs elsewhere". |
| D19 | **`--purl` mode is the same pipeline minus the input stage.** Requests are the validated purls; there is no graph, so `paths` and `services_affected` stay unset and exposure is assumed. | The hook needs "is this one package dead?" in seconds. Reusing everything after the input stage means no second scorer, table or schema. |
| D3 | **A service is a manifest directory** (EX-6): a directory that directly contains at least one recognised lockfile. One Syft run, one `ServiceInput`, one set of scopes per service. | `core.graph` is built for this and `services_affected` depends on it. A single Syft run over the repo root would give one mixed SBOM with no per-service root. |
| D4 | **Syft is run once per service directory, sequentially,** with an argv list (no shell), a timeout, a cleared environment and `--exclude` for nested service directories. The version must equal the pinned `1.56.0`. | Verified against the real Syft 1.56.0 on 11 Nov 2026: `syft dir:<root>` recurses into nested directories and counts their packages again, `--exclude './sub/**'` removes them, and a cleared environment (only `PATH`, `SYFT_CHECK_FOR_APP_UPDATE=false`) works. |
| D5 | **`--sbom FILE` is one service, `"."`.** Scopes come from lockfiles directly in `PATH` (not recursive). Syft is not located or run. | The simplest input that serves PRD EX-3 for local use. A multi-SBOM form is not needed for the skeleton. |
| D6 | **Syft or SBOM failure is fatal (exit 3). Lockfile failure is a warning.** | Silent loss of a whole service would let a gate pass on an unscanned service. A lockfile only supplies scope. When it is missing, `core.graph` assumes `runtime`, the highest exposure weight, so the failure errs towards more priority, not less. |
| D7 | **Environment is read in exactly one module, `cli/__main__.py`,** which builds a `CliEnvironment` and passes it to `app.run`. | User requirement and `security.md` T6. Every other module takes values as arguments, which also keeps the tests free of `monkeypatch.setenv`. |
| D8 | **Exposure is plumbed by the CLI, not by `sources`.** After `autopsy` returns `Signals`, the CLI sets `paths` and `services_affected` with `dataclasses.replace` from `exposure_inputs(node)`, then calls `score_package`. | `autopsy-sources` D12: `sources` never sets these. Without this step every package keeps `exposure_assumed = True` and ranking ignores the graph. |
| D9 | **The CLI contains no model logic.** Scoring is `score_package`, ordering is `sort_results`, and `why` text is composed only from fields those return plus the evidence. No threshold, weight or formula appears in `backend/cli/`. | Product principle 1 (explainable, deterministic) and `mortality-model.md` (no model literals in code). |
| D10 | **`--fail-on` takes a comma-separated set** of `dead`, `cursed`, `ailing`. A package matches if it is in any named class. `ailing` does not include Dead. | PRD H6 writes `--fail-on dead,cursed`, which is a set. Cursed is an overlay and is not ordered against Ailing, so a severity threshold cannot express it. See Q2. |
| D11 | **Exit codes are defined here** (the PRD does not specify them): 0 clean, 1 gate tripped, 2 usage error, 3 input or tool error, 4 internal error. | CI needs "the gate fired" to differ from "the tool broke". 2 matches `argparse`. |
| D12 | **The JSON report has a name and an integer version** (`"schema": "graveyard.autopsy"`, `"schema_version": 1`). Adding keys keeps 1. Renaming, removing or retyping a key, or changing a meaning, bumps it. | "Stable schema, versioned." Consumers (GitHub Action, Coroner's Report, MCP) can check one field. |
| D13 | **Everything printed to a terminal is sanitised.** Control characters and bidirectional overrides in any cell become `U+FFFD`. | Package names come from files the user did not necessarily write. Escape sequences in a table are a terminal injection. |
| D14 | **`as_of` defaults to today (UTC) from the injected `Clock`;** `--as-of YYYY-MM-DD` overrides it. | `core.scoring` never reads a clock. Tests pass `--as-of 2026-11-03`, the date the cassette was recorded for. |
| D15 | **The autopsy cache is the in-process `MemoryCache`.** | A persistent cache is the DynamoDB cache of AU-5 (infra). A local disk cache is not needed to make the pipeline work. |
| D16 | **The default table lists what needs attention,** every package that is not Alive or Resting, or is Cursed. `--all` lists every package. The JSON always lists every package. | PRD GY-1: Alive and Resting are counts, not tombstones. The table is the "what do I look at" view. |
| D17 | **No LLM, no network of its own.** The CLI imports neither `httpx` nor `urllib`. All network access is `sources`, which has the fixed host allow-list. | `security.md` T1, T2. There is no prompt-injection surface to defend. |
| D18 | **One test seam: `app.run(argv, *, env, out, err, transport=None, clock=None) -> int`.** Syft is faked by a real stub executable passed with `--syft`, not by a mock. | The tests exercise argument parsing, the subprocess call, discovery, the pipeline and rendering together, with the network replaced by the recorded cassette. Single-package tests use a test-only transport that answers from the cassette and derives the two batch endpoints (OSV `querybatch`, npm downloads) for a subset of the recorded packages (design §9.4). |

---

## Dependency, packaging and purity

| ID | Requirement |
|----|-------------|
| CLI-DEP-1 | **THE SYSTEM SHALL** add no runtime or dev dependency. The CLI uses `argparse`, `subprocess`, `json`, `pathlib`, `asyncio`, `shutil` and `dataclasses` from the standard library, plus `httpx` only through `sources`. The `hatchling` build backend of CLI-DEP-3 is a build requirement in `[build-system]`, not a runtime or dev dependency. |
| CLI-DEP-2 | `backend/pyproject.toml` SHALL list `cli` next to `core` and `sources` in `[tool.mypy] files`, `[tool.pytest.ini_options] testpaths` and `[tool.ruff.lint.isort] known-first-party`. `uv run ruff check`, `uv run ruff format --check`, `uv run mypy --strict core sources cli` and `uv run pytest -q` SHALL pass. No blanket `type: ignore`. |
| CLI-DEP-3 | **Packaging (D2).** `backend/pyproject.toml` SHALL have: <br>• `[build-system]` with `requires = ["hatchling==<exact version>"]` (an exact pin, no range, no `latest`) and `build-backend = "hatchling.build"`; <br>• `[tool.uv] package = true`; <br>• `[project.scripts] graveyard = "cli.__main__:main"`; <br>• `[tool.hatch.build.targets.wheel] packages = ["core", "sources", "cli"]`, with `tests` directories and `__pycache__` excluded and non-Python package data included, so the wheel holds `core/scoring/weights.v1.yaml`. <br>`uv.lock` SHALL be regenerated by `uv` and the diff reviewed. `uv sync`, `uv run pytest -q`, `uv run graveyard --version` and `uv run python -m cli --version` SHALL work, the last two printing the same line and exiting 0. A wheel built with `uv build --wheel` SHALL contain `cli/__main__.py` and `core/scoring/weights.v1.yaml` and no `tests/` path (checked by hand once, CLI-TEST-12). |
| CLI-DEP-6 | A fast test `cli/tests/test_packaging.py` SHALL parse `pyproject.toml` with `tomllib` and fail if the `hatchling` pin is not exact, `package` is not `true`, the script entry is missing or wrong, or the wheel `packages` list lacks one of `core`, `sources`, `cli`. |
| CLI-DEP-4 | `core` and `sources` SHALL NOT import `cli`. `cli` MAY import `core` and `sources`. `cli` SHALL import `core.scoring` only for `score_package`, `sort_results` and the types `ScoringResult`, `BaseState`, `Signals`. |
| CLI-DEP-5 | **Guard test** `cli/tests/test_guards.py` (modelled on `sources/tests/test_silence.py`), parametrised by glob over `cli/*.py`: <br>• `os.environ`, `os.getenv`, `environ` and `getenv` appear only in `__main__.py`; <br>• `subprocess` is imported only by `syft.py`, no call passes `shell=True`, and `os.system` / `os.popen` are never used; <br>• no `print`, `input`, `logging` or `warnings` anywhere (output goes through the `out` and `err` streams); <br>• `httpx`, `urllib`, `socket` and `requests` are never imported. <br>Each rule has a bad-sample test so the guard cannot pass vacuously, and a test that the glob finds every module. |

---

## Command line

| ID | Requirement |
|----|-------------|
| CLI-CMD-1 | **THE SYSTEM SHALL** accept `graveyard autopsy {PATH [--sbom FILE] \| --purl PURL [--purl PURL …]} [--json FILE] [--fail-on LIST] [--as-of YYYY-MM-DD] [--all] [--syft PATH] [--syft-timeout SECONDS]`. `PATH` is a directory that exists. `--syft-timeout` is a positive finite number, default 120. `--syft` defaults to `shutil.which("syft")`. |
| CLI-CMD-2 | `graveyard --version` and `graveyard --help` (also `graveyard autopsy --help`) SHALL exit 0. `--help` includes the exit-code table (CLI-GATE-4) as an epilog. |
| CLI-CMD-3 | `--fail-on` SHALL parse a comma-separated list, case-insensitive, whitespace-trimmed, of `dead`, `cursed`, `ailing`. An empty list, an empty item or an unknown word SHALL exit 2 with a message naming the allowed words. |
| CLI-CMD-4 | `--as-of` SHALL accept an ISO date only. Anything else, including a datetime or a date in the future of the clock, SHALL exit 2. |
| CLI-CMD-5 | A missing `PATH` with no `--purl`, a `PATH` that is not a directory, `PATH` together with `--purl`, `--sbom` together with `--purl`, an unknown option, a missing `--sbom` file or a non-positive `--syft-timeout` SHALL exit 2 with one line on stderr and the usage line. No traceback. |
| CLI-CMD-6 | The CLI SHALL have **no option that takes a token or any other secret.** |

---

## Discovery and lockfiles (EX-2, EX-6, EX-8)

| ID | Requirement |
|----|-------------|
| CLI-DISC-1 | **THE SYSTEM SHALL** walk `PATH` with `os.walk(followlinks=False)`, in sorted order, skipping directories named `node_modules`, `__pycache__`, `venv`, `site-packages`, and every directory whose name starts with `.`. |
| CLI-DISC-2 | A directory is a **service** when it directly contains a file named `package-lock.json`, `uv.lock`, `poetry.lock`, or matching `requirements*.txt`. Symlinked files are ignored. The service path is the POSIX path relative to `PATH`, `"."` for the root. Services are sorted by path. |
| CLI-DISC-3 | More than `DEFAULT_MAX_SERVICES` (50) services SHALL exit 3 with a message that says to narrow `PATH`. No services and no `--sbom` SHALL exit 3 with a message that names the recognised lockfiles and suggests `--sbom`. A service whose relative path contains any of `* ? [ ] { }` SHALL exit 3 with a message to rename the directory, because the path is used in a Syft `--exclude` glob (design §11). |
| CLI-SCOPE-1 | For each service the CLI SHALL read every recognised lockfile in that directory, UTF-8, and call the matching parser: `package-lock.json` → `parse_package_lock`, `uv.lock` → `parse_uv_lock`, `poetry.lock` → `parse_poetry_lock`, `requirements*.txt` → `parse_requirements_txt`. |
| CLI-SCOPE-2 | A lockfile that cannot be read or parsed (`OSError`, `UnicodeDecodeError`, `ValueError`, a file above the parser's size limit) SHALL produce a CLI warning `LOCKFILE_UNREADABLE` with the service and file name and SHALL be skipped. The run continues (D6). |
| CLI-SCOPE-3 | When a service has several lockfiles, their `ScopeResult` values SHALL be merged into one: for a key present in both, `runtime` wins (the same rule as `DG-SCP-3`); warnings are concatenated. The merge is commutative, associative and idempotent. |
| CLI-SCOPE-4 | `requirements*.txt` SHALL be treated as runtime, as EX-8 says, including `requirements-dev.txt`. This overstates the exposure of dev requirement files and is documented in the README as a known limitation. |
| CLI-SCOPE-5 | Lockfiles are only parsed. Nothing in them is executed, installed or resolved (T9). |

---

## Syft and SBOM input (EX-S1, T9)

| ID | Requirement |
|----|-------------|
| CLI-SYFT-1 | `cli/syft.py` SHALL define one constant `SYFT_VERSION = "1.56.0"`. Before the first scan the CLI SHALL run `[syft, "--version"]` and require the output to be `syft 1.56.0`. Any other output SHALL exit 3 with the version found (printed only if it matches `[0-9A-Za-z.+-]{1,40}`) and the version required. |
| CLI-SYFT-2 | Per service, the CLI SHALL run exactly `[syft, "dir:<absolute service directory>", "-q", "-o", "cyclonedx-json", ("--exclude", "./<relative nested service>/**")…]` with `shell=False`, `stdin=DEVNULL`, `capture_output=True`, `timeout=--syft-timeout`, `check=False` and the environment from `CliEnvironment.syft_env`. Nested services are the other services whose path starts with this service's path (D4). |
| CLI-SYFT-3 | A missing executable, a non-zero exit, a timeout, output above 32 MiB, output that is not a JSON object, or a BOM that `build_graph` rejects SHALL exit 3 with a fixed message naming the service. **Syft's stderr is never echoed.** |
| CLI-SYFT-4 | The CLI SHALL NOT install, download or update Syft. When it is not found the message says how to install the pinned version and that `--sbom` avoids it. |
| CLI-SBOM-1 | `--sbom FILE` SHALL read the file (at most 32 MiB), parse it as JSON and use it as the single service `"."`. A file that is unreadable, too large, not JSON or not an object exits 3. Structural CycloneDX errors come from `build_graph` (`ValueError`) and exit 3. |
| CLI-SBOM-2 | With `--sbom`, scope lockfiles are looked up directly in `PATH` (non-recursive). With none present, `build_graph` emits its `SCOPE_ASSUMED` warning and the run continues. |

---

## Single-package mode (`--purl`; D19; hook H9)

| ID | Requirement |
|----|-------------|
| CLI-PURL-1 | `--purl PURL` SHALL be repeatable. Exactly one input is required: `PATH` or at least one `--purl`. `--purl` with `PATH` or with `--sbom` SHALL exit 2 (CLI-CMD-5). |
| CLI-PURL-2 | **Validation before any I/O.** Each value SHALL be parsed with `core.purl.parse_purl`. A value that does not parse, names an ecosystem other than npm or PyPI, or has no version SHALL exit 2 with one line on stderr that gives the argument's position and the reason from a fixed template; the offending text is shown only after `sanitise` and truncated to 100 characters. |
| CLI-PURL-3 | Purls SHALL be de-duplicated by `package_key`, keeping the smallest canonical purl, so `sort_results` never sees a duplicate. |
| CLI-PURL-4 | In this mode the CLI SHALL NOT discover, locate or run Syft, read lockfiles or SBOMs, or call `build_graph`. The requests are `(canonical purl, as_of)` for the validated purls; collection, scoring (with `paths` and `services_affected` unset, so `exposure_assumed` is true), ranking, table, JSON, gate and exit codes are those of project mode. `--syft` and `--syft-timeout` are accepted and have no effect. |
| CLI-PURL-5 | In the table, `EXPOSURE` is `assumed` (CLI-OUT-5). In the JSON, `input.mode` is `"purl"`, `input.services` and `input.lockfiles` are empty, and for each package `manifests`, `path_infos` and `example_paths` are empty arrays while `direct`, `scope` and `services_affected` are `null` (CLI-JSON-3). |
| CLI-PURL-6 | The mode SHALL work without a token (CLI-ENV-4). For the hook, the README SHALL show the command `graveyard autopsy --purl <purl> --fail-on dead,cursed` and the exit-code mapping the hook needs (see "Belongs elsewhere": the Kiro docs disagree on whether exit 1 blocks, so the wrapper blocks with exit 2 and fails open on any CLI error). |

---

## Pipeline (AU-1…AU-4, §7)

| ID | Requirement |
|----|-------------|
| CLI-PIPE-1 | **THE SYSTEM SHALL** run, in project mode and in this order: discover services → obtain one BOM and one merged `ScopeResult` per service → `build_graph` with default limits → build the request list `(node.purl, as_of)` for every node → `SourceSession.collect` → set exposure → `score_package` → `sort_results`. In `--purl` mode the first four steps are replaced by CLI-PURL-4 and "set exposure" is skipped. |
| CLI-PIPE-2 | The request list SHALL be split into chunks of at most `Limits.max_packages_per_call` and collected in order inside **one** `SourceSession`, so limiters and cache are shared and no input is rejected for size. |
| CLI-PIPE-3 | For every `SourceResult` with `signals`, the CLI SHALL replace `Signals.paths` and `Signals.services_affected` with the two values of `exposure_inputs(node)` (D8) and then call `score_package(signals)` with the default weights. A node with no path keeps `exposure_assumed = True`. |
| CLI-PIPE-4 | A `SourceResult` with `error` (an item error) SHALL NOT be scored or ranked. It SHALL be reported in the JSON `errors` array and counted in the summary. It does not change the exit code. |
| CLI-PIPE-5 | The ranking SHALL be exactly `sort_results` (priority desc → `services_affected` desc → purl asc; Unknown after scored). The CLI SHALL NOT sort, tie-break or filter before it (D9). |
| CLI-PIPE-6 | `as_of` SHALL be `--as-of` or the UTC date of `Clock.now()` (D14). It is the `as_of` of every request. |
| CLI-PIPE-7 | `SourcesConfig.default(contact=…)` and `Limits` SHALL be used unchanged. The CLI does not read SSM and does not tune hosts. |
| CLI-PIPE-8 | An unexpected `Exception` anywhere in the run SHALL exit 4 with `internal error: <ExceptionType>` on stderr, never the exception text. `KeyboardInterrupt` and `SystemExit` are not caught by this rule. |

---

## Terminal table (AU-3, product principle 3)

| ID | Requirement |
|----|-------------|
| CLI-OUT-1 | **THE SYSTEM SHALL** print to stdout a table with exactly these columns, in this order: `STATE`, `PACKAGE`, `WHY`, `EXPOSURE`, `PRIORITY`, one row per package in rank order (CLI-PIPE-5). |
| CLI-OUT-2 | `STATE` is the base state (`Dead`, `Ailing`, `Alive`, `Resting`, `Unknown`) followed by ` · Cursed` if the Cursed overlay holds, else ` · Wounded` if the Wounded overlay holds (the UI shows Cursed when both apply, §7.4). |
| CLI-OUT-3 | `PACKAGE` is `<ecosystem> <name>@<version>`, for example `npm request@2.88.2`. |
| CLI-OUT-4 | `WHY` SHALL be composed by the pure function `why(...)` only from `ScoringResult` fields, the package's `Signals` and fixed templates. Rules: <br>• declared death: `declared dead`; <br>• Dead by score or Ailing: the two signals with the largest `contributions`, each rendered from its raw value (`last release 2014-06`, `last push 2016-02`, `Scorecard maintained 0/10`, `1 committer in 12 months`, `88 open / 12 closed issues`, `Scorecard overall 3.4/10`); <br>• Cursed: `N advisories with no fix`; <br>• Wounded, not Cursed: `fix available` for advisories, `upgrade advised` for S1b; <br>• Unknown: `no scored signals`; <br>• Resting: `quiet but healthy`; Alive with no overlay: `—`. <br>Fragments are joined with `; ` in this order. `why` never reads free text from a source. |
| CLI-OUT-5 | `EXPOSURE` is `direct` or `transitive`, then `runtime` or `dev`, read from the first member of `GraphNode.path_infos` (which `core.graph` sorts runtime before dev, then direct before transitive; this is display only and the number that ranks is `ScoringResult.exposure`), then ` · N services` when `services_affected` > 1, and `assumed` instead of all of that when `exposure_assumed` is true. |
| CLI-OUT-6 | `PRIORITY` is the priority to one decimal place, or `—` for Unknown. Rounding happens only here. |
| CLI-OUT-7 | By default the table lists every package that is not (Alive or Resting) or is Cursed (D16). `--all` lists every package. A footer line always follows: total packages and counts per state, plus Cursed and Wounded counts, and the number of rows hidden. |
| CLI-OUT-8 | **Sanitisation (D13).** Every cell SHALL be passed through `sanitise`, which replaces C0 and C1 control characters, `DEL`, and the bidirectional controls U+202A–U+202E and U+2066–U+2069 with U+FFFD, and keeps all other characters. `sanitise` is idempotent. |
| CLI-OUT-9 | Column widths SHALL come from the content and `CliEnvironment.width` (default 100, minimum 60). `WHY` is shortened with `…` first. The table is plain text: no colour, no box drawing beyond spaces, no emoji. |
| CLI-OUT-10 | Stdout holds only the table and footer. Warnings, the gate message and errors go to stderr. Output is a pure function of the report, so two runs with the same inputs and clock give identical bytes. |

---

## JSON report (AU-3, D12)

| ID | Requirement |
|----|-------------|
| CLI-JSON-1 | `--json FILE` SHALL write the report after the table, whether or not the gate tripped, as UTF-8 JSON with `indent=2`, `allow_nan=False`, a fixed key order and a trailing newline. It is not written for exit codes 2, 3 or 4. A write failure exits 3. |
| CLI-JSON-2 | The document SHALL have the top-level keys, in order: `schema`, `schema_version`, `model_version`, `as_of`, `input`, `summary`, `packages`, `errors`, `warnings`. The full shape is in design §7. |
| CLI-JSON-3 | `packages` SHALL list **every** scored package in rank order. Each carries `rank`, `purl`, `key`, `ecosystem`, `name`, `version`, `state` (the `BaseState` value), `dead_reason`, `cursed`, `wounded`, `mortality`, `confidence`, `priority`, `exposure`, `exposure_assumed`, `services_affected`, `direct`, `scope`, `manifests`, `path_infos`, `example_paths`, `why`, `normalised_risks`, `contributions`, `evidence`, `repo`, `repo_via`, `resolved_version`, `latest_version` and `warnings`. Numbers are the unrounded values from `core.scoring`. In `--purl` mode (no graph) `services_affected`, `direct` and `scope` are `null` and `manifests`, `path_infos` and `example_paths` are empty (CLI-PURL-5); in project mode they are an integer, a boolean and `"runtime"` or `"dev"`. |
| CLI-JSON-4 | `evidence` SHALL hold the 11 `EVIDENCE_KEYS` of the package's `SourceResult`, each as `value`, `source_url`, `fetched_at` (ISO 8601 UTC string or null), `extra_source_urls` and `note`, so every point is traceable to a link (principle 1). |
| CLI-JSON-5 | `warnings` SHALL list, each tagged with `origin`: `graph` (every `GraphWarning`), `cli` (CLI warnings: `LOCKFILE_UNREADABLE`, `GITHUB_TOKEN_MISSING`, `GITHUB_TOKEN_INVALID`) and `source` (a package's `SourceWarning` values appear under that package, and a count per code appears in `summary`). |
| CLI-JSON-6 | `summary` SHALL carry the package count, count per state, `cursed`, `wounded`, `item_errors`, `degraded` (true when any source warning or CLI token warning exists), the warning counts, the source statistics (`SourceStats`), and `gate`: `{fail_on, tripped, matches}`, plus the final `exit_code`. |
| CLI-JSON-7 | The report SHALL contain no absolute filesystem path, no environment value and no token. Service paths are relative to `PATH`. |
| CLI-JSON-8 | Given identical inputs, `as_of`, cassette and clock, the file SHALL be byte-identical across runs. |
| CLI-JSON-9 | The README SHALL document the schema and the versioning rule of D12. A test SHALL compare the structural shape (keys, and for each key the set of allowed JSON types, recursively) of the end-to-end reports of both modes with one committed shape file, so an accidental change to the schema fails a test. The shape file lists `["integer", "null"]` and similar for the fields that are null in `--purl` mode. |

---

## Gating and exit codes (D10, D11)

| ID | Requirement |
|----|-------------|
| CLI-GATE-1 | **(Amended in round 2: a package must also be `gate_eligible`, CLI-EVID-4.)** A package **matches** a class when: `dead` → `base_state == DEAD`; `cursed` → `cursed` is true; `ailing` → `base_state == AILING`. The gate **trips** when at least one ranked package matches at least one class in `--fail-on`. Unknown packages never match. |
| CLI-GATE-2 | Without `--fail-on` the gate never trips. |
| CLI-GATE-3 | When the gate trips, stderr SHALL say how many packages match and list up to 10 of them (`purl`, sorted in rank order). When `--fail-on` is set and the run is degraded or has Unknown packages, stderr SHALL say that the gate was evaluated on partial evidence and give the number of Unknown packages. The exit code is not changed by degradation (Q7). |
| CLI-GATE-4 | The exit codes SHALL be: <br>**0** the run completed and the gate did not trip (including degraded runs and runs with item errors); <br>**1** the run completed and the gate tripped; <br>**2** usage error (CLI-CMD-3…5); <br>**3** input or tool error: no lockfiles, too many services, Syft missing, wrong version, failed or timed out, unreadable or invalid SBOM, or a write failure for `--json`; <br>**4** internal error (CLI-PIPE-8). <br>The table SHALL be in the README, in `--help`, and in `ExitCode` (`IntEnum`). A test SHALL fail if the README table and `ExitCode` disagree. |
| CLI-GATE-5 | Codes 2, 3 and 4 are decided before or instead of the gate; the gate runs only after a complete analysis. When a run has completed, the exit code is 1 if the gate tripped, else 0. |

---

## Environment and secrets (T6; D7)

| ID | Requirement |
|----|-------------|
| CLI-ENV-1 | `cli/__main__.py` SHALL be the only module that reads the environment. It reads `GITHUB_TOKEN`, `GRAVEYARD_CONTACT`, an allow-list of variables for Syft (`PATH`, `HOME`, `TMPDIR`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`), and the terminal width, and builds a `CliEnvironment` (design §4). |
| CLI-ENV-2 | `GITHUB_TOKEN` SHALL be wrapped in `SecretToken` in `__main__` and travel only as a `SecretToken`. A value that is empty or whitespace-only is treated as **absent** (decided in review: GitHub Actions renders an absent secret as `""`), so the run warns `GITHUB_TOKEN_MISSING`. Any other value that is not a valid token (it contains whitespace or control characters inside it, or is over 255 characters) is dropped and `GITHUB_TOKEN_INVALID` is warned, without the value. |
| CLI-ENV-3 | The token SHALL be passed only to `SourceSession(token=…)`. It SHALL NOT be passed to Syft (`syft_env` does not contain it), put in argv, written to stdout, stderr or the JSON file, or interpolated into any message or exception text. |
| CLI-ENV-4 | **Without a token the run works, degraded.** `sources` marks every GitHub signal missing with `GITHUB_DISABLED` and confidence falls. The CLI adds one `GITHUB_TOKEN_MISSING` warning (also for an empty or whitespace-only `GITHUB_TOKEN`, CLI-ENV-2) and prints it once on stderr. The exit code is unchanged. |
| CLI-ENV-5 | `GRAVEYARD_CONTACT`, when set and valid, is the contact for `SourcesConfig`. Otherwise a code constant `DEFAULT_CONTACT` is used (Q5). A contact that `SourcesConfig` rejects falls back to the default. |
| CLI-ENV-6 | The Syft environment SHALL contain only the allow-listed variables that are set, plus `SYFT_CHECK_FOR_APP_UPDATE=false`. **Amended in round 2 (CLI-DEV-1):** plus `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true`, set by `syft.py`. |

---

## Security (T1, T2, T6, T9; `security.md`)

| ID | Requirement |
|----|-------------|
| CLI-SEC-1 | Nothing from the scanned project is executed or installed. Syft only reads files, and lockfiles are only parsed (T9). The CLI runs no package manager and no project script. |
| CLI-SEC-2 | The CLI builds no URL and fetches nothing itself (D17). It accepts no URL as input. |
| CLI-SEC-3 | All values the CLI prints come from validated fields or fixed templates. Package names and versions pass `core.purl`; they and every other cell pass `sanitise` (CLI-OUT-8). JSON string escaping is `json.dumps`. |
| CLI-SEC-4 | Only the path the user gave with `--syft`, or the one `shutil.which` found, is executed, as an argv element, never through a shell. |
| CLI-SEC-5 | A test SHALL run the end-to-end scenario with a token of a distinctive value and assert that the value appears nowhere in stdout, stderr or the JSON file. (The transport legitimately sees it in the `Authorization` header sent to `api.github.com`; that is `sources` behaviour and is not asserted here.) |

---

## Tests (no network)

| ID | Requirement |
|----|-------------|
| CLI-TEST-1 | **No network.** `cli/tests/conftest.py` SHALL install an autouse fixture that makes `socket.socket.connect` and `socket.create_connection` raise. Every pipeline test SHALL pass an `httpx.MockTransport`: one that replays the recorded cassette (`replay_transport`, or the derived `subset_replay_transport`) where the scenario uses recorded data, asserting `log.unmatched == []`; and a transport that fails every request, or fails the test if called, for the chunking and rejection tests. |
| CLI-TEST-2 | **(Amended in round 2: the SBOMs are real Syft 1.56.0 output, CLI-FIX-1.)** **Fixture project** `cli/tests/fixtures/anchors-project/`: two services, `web/` (a `package-lock.json`) and `api/` (a `uv.lock`), containing the nine anchor packages at the exact versions in `core/scoring/tests/fixtures/anchors/*.json`. The lockfiles and the CycloneDX BOMs (kept outside the project, in `fixtures/sboms/`) are hand-written, with real names and versions and relationships chosen to exercise exposure (design §9). A README in the fixture directory states that they are synthetic. |
| CLI-TEST-3 | **End-to-end test** SHALL run `app.run(["autopsy", <project>, "--syft", <stub>, "--as-of", "2026-11-03", "--json", <file>, "--all"], …)` with a token and the replay transport, and assert: <br>• the exit code is 0, and `--fail-on dead` gives 1; <br>• the nine states, dead reasons and overlays equal the MM-ANC table (request Dead declared Cursed; node-uuid and left-pad Dead declared; pycrypto Dead by score Cursed; nose Dead by score; six Resting; express, uuid, moment Alive Wounded); <br>• the rank order equals the committed literal `pycrypto, left-pad, request, node-uuid, nose, six, uuid, moment, express` (design §9.2); <br>• that order differs from the order of the same packages with exposure assumed, so the test fails if exposure is not plumbed (D8); <br>• `services_affected`, `direct` and `scope` of at least four packages; <br>• the table and the JSON list the same packages in the same order. |
| CLI-TEST-4 | **Variants:** `--sbom` with a combined BOM (same states, `input.mode == "sbom"`, one service); no token (exit 0, `GITHUB_DISABLED` source warnings, `GITHUB_TOKEN_MISSING`, lower confidence for at least one package, `degraded` true); the `--fail-on` matrix (`dead` → 1, `cursed` → 1, `ailing` → 0, `ailing,cursed` → 1, none → 0); item error (a unit test of `pipeline.rank` with a hand-built `BatchResult`, because `core.graph` already drops unsupported purls and a real graph cannot produce one: the package is reported under `errors`, not ranked, and the exit code is unchanged); an unreadable lockfile (warning, exit 0). |
| CLI-TEST-5 | **Stub Syft** (a real executable script written to `tmp_path`, shebang = `sys.executable`) SHALL cover: `--version` output accepted and rejected; the argv received (no shell, `dir:` absolute path, `-q`, `-o cyclonedx-json`, `--exclude` for a nested service); a non-zero exit; a timeout (stub sleeps, `--syft-timeout 0.5`); output that is not JSON; the cleared environment (stub reports its environment, which must not contain `GITHUB_TOKEN`). |
| CLI-TEST-6 | **Property tests** (`@pytest.mark.property`): `sanitise` is idempotent and its output has no character from the forbidden set; `merge_scopes` is commutative, associative, idempotent and runtime wins; the gate is monotone (adding a class to `--fail-on` never turns a tripped gate into an untripped one); `why` is total over generated valid `Signals` and its output passes `sanitise` unchanged; `report_to_dict` for generated rows is `json.dumps(…, allow_nan=False)`-safe and has the same keys for every row. |
| CLI-TEST-7 | **Determinism.** Two runs of the end-to-end scenario SHALL produce byte-identical stdout and JSON. |
| CLI-TEST-8 | **Syft pin.** A test SHALL assert `SYFT_VERSION == "1.56.0"` and that `docs/SPIKES.md` names the same version, so a bump has to touch both. (The Syft Lambda image pin is checked by the infra spec when that image exists.) |
| CLI-TEST-9 | **Real Syft smoke test** (manual, not part of CI, because CI has no Syft and the run would hit the network): the README documents one command that runs `graveyard autopsy cli/tests/fixtures/anchors-project/` with the installed Syft 1.56.0. A task runs it once, checks that Syft sees the same nine packages as the stub BOMs, and records the result in `docs/KIRO_JOURNAL.md`. |
| CLI-TEST-10 | **Coverage gate (decided in review).** `uv run pytest cli --cov=cli --cov-report=term-missing --cov-fail-under=85` SHALL pass. This extends the 85 % line-coverage gate of `testing.md`, which names `core` and `rites`, to `cli`; `testing.md` still names only `core` and `rites`; the final report lists that one-line edit. |
| CLI-TEST-11 | **Single-package end-to-end** (CLI-PURL-*), run through `app.run` with no token, the cassette-derived transport of design §9.4 and `log.unmatched == []`: <br>• `autopsy --purl pkg:npm/request@2.88.2 --fail-on dead` exits **1**, and the JSON has `input.mode == "purl"`, one package, state Dead, `dead_reason == "declared"`, `exposure_assumed == true`; <br>• `autopsy --purl pkg:npm/express@4.17.1 --fail-on dead` exits **0** (state Alive); <br>• nine `--purl` arguments (the anchors, with a token, request body identical to the recording so the cassette is replayed as recorded) give the exposure-assumed order `pycrypto, request, nose, left-pad, node-uuid, six, uuid, moment, express` and the MM-ANC states; <br>• an invalid purl, a purl without a version, a `pkg:maven/…` purl, `--purl` with `PATH`, and `--purl` with `--sbom` each exit **2** with no network request and no Syft lookup; <br>• a repeated purl is analysed once; <br>• `--syft /nonexistent` with `--purl` does not fail. |
| CLI-TEST-12 | **Packaging check (manual, once).** After CLI-DEP-3: `uv build --wheel --out-dir <tmp>`, list the wheel with `unzip -l`, and record in `docs/KIRO_JOURNAL.md` that it holds `cli/__main__.py`, `core/scoring/weights.v1.yaml`, `core/` and `sources/` modules, and no `tests/` path. |

---

## Belongs elsewhere

Anything below was considered and left out on purpose. Each item names where it belongs.

| Item | Belongs in | Why not here |
|------|------------|--------------|
| Persistent autopsy cache (24 h TTL) | `infra-serverless` (DynamoDB, AU-5) | The CLI's `MemoryCache` is enough for one run. A local disk cache would be a second cache design. |
| Syft Lambda image and its pin | `docker/syft-lambda/` and `infra-serverless` | The image must use the same `1.56.0`. `CLI-TEST-8` pins the CLI side; the infra spec adds the check on the image side. |
| GitHub App installation tokens, Reader app | `github-app-pull-requests`, `infra-serverless` | The CLI uses a token the user supplies for local runs. `tech.md` says product auth is a GitHub App, not a PAT. A personal token is acceptable for a developer's own machine and must not be documented as the product's auth. |
| SSM runtime config (limits, kill switch, model IDs) | `infra-serverless` | The CLI runs outside AWS. It uses `SourcesConfig.default`. |
| `GRAVEYARD_KILL_SWITCH` / cached-demo mode | `infra-edge`, `graveyard-ui` | Applies to the hosted product only. |
| **Rename to `autopsy` in the PRD, `structure.md` and hook H6** (decided Q4) | you, as a documentation edit, or the `kiro-power` spec. The tasks of this spec do not edit the PRD or steering; the final report lists the edits | PRD §14 and `structure.md` list the CLI as `(check, check-install, scan)`. Hook H6 (`dogfood-autopsy`) runs `graveyard check web/package-lock.json backend/uv.lock --fail-on dead,cursed`: it must become `graveyard autopsy <dir> --fail-on dead,cursed`, because `autopsy` takes a directory and not lockfile paths. Hook H9 (`dead-install-blocker`) and the Power's hook KP-3 call `graveyard check-install "$COMMAND"`; they will parse the command and then call `graveyard autopsy --purl …`. **Done by `kiro-power` (T13.2):** PRD (H9, KP-1…3, §14) and `structure.md` now name `autopsy` and `check-install`; H9 calls `graveyard check-install` with the command read from the stdin payload (spike KP-S1: `tool_input.command`, envelope `cwd`, exit 2 blocks, Kiro 1.4.86), not `"$COMMAND"`. |
| **Hook exit-code mapping** | `kiro-power` (KP-3, H9) | **What the docs say (checked 11 Nov 2026).** [Hook actions](https://kiro.dev/docs/hooks/actions/) (updated 10 Oct 2026), for the shell-command action: exit 0 adds stdout to the agent's context; any other exit code sends stderr to the agent, and for Pre Tool Use also blocks the tool invocation. [Hook types](https://kiro.dev/docs/hooks/types/) (updated 6 Nov 2026) says a Pre Tool Use hook "can validate and block tool usage" but gives no exit-code table for it (it does give one for Pre Compaction: exit 2 cancels). The CLI-specific page `kiro.dev/docs/cli/hooks/` now redirects to `/docs/hooks/`, so I found no official page that separates IDE and CLI behaviour, and no official page for the `permissionDecision` stdout JSON. Third-party Kiro CLI v3 write-ups say exit 2 blocks and exit 1 only warns; those are not official. **Consequence:** the two readings disagree about exit 1, so the wrapper must not depend on it. It SHALL exit **2** with the reason on stderr to block (blocks under both readings), exit **0** to allow, and never exit 1. **Decided mapping (fail open, block only when sure), for the `kiro-power` wrapper around `graveyard autopsy --purl <purl> --fail-on dead,cursed`:** CLI exit **0** → wrapper exit **0**; CLI exit **1** (the gate tripped) → wrapper exit **2** with the reason on stderr; CLI exit **2, 3 or 4** (usage error, input or tool error, internal error) → wrapper exit **0** with one line on stdout, `graveyard could not check <purl>: <reason>`. The wrapper never exits 1. Stdout from an exit-0 hook is added to the agent's context, so the "could not check" line reaches the agent without blocking the install. **Round 2:** the CLI no longer exits 1 for a Dead-by-score package whose score rests on skipped data (CLI-EVID-1), so a token-less `--purl` check does not block a package such as `six`; a wrapper that reads the `--json` report can show `unverified_reason` as the "could not fully check" notice. `kiro-power` spec KP-S1 must test the real behaviour in the IDE and in CLI V3 before relying on it. The CLI's own codes are not changed. **Done by `kiro-power` (T13.2), spike KP-S1 (Kiro 1.4.86, `docs/SPIKES.md`):** the hook receives the command as `tool_input.command` in stdin JSON, with the workspace in the envelope `cwd`; exit 2 blocks. The mapping lives in the hook's guarded shell snippet and in `check-install`, which returns only 0 or 2 (2 blocks, every other outcome allows). Measured in the IDE build only; CLI V3 was not tested. |
| `check-install` (parse `npm install x`, `pip install y` into purls) and `scan` subcommands | `kiro-power`, `vigil` | They reuse `cli.pipeline`. `--purl` mode is the call they make. **`check-install` done by `kiro-power` (T13.2)**, reading the command from the stdin payload (spike KP-S1: `tool_input.command`, envelope `cwd`, exit 2 blocks, Kiro 1.4.86). `scan` remains with `vigil`. |
| **Lambda packaging impact of D2** | `infra-serverless` | With `package = true` the backend is a wheel. The wheel's `packages` list must name every top-level package a function needs and be extended when `workflow`, `api`, `rites`, `narrate` or `mcp` are added; `cli` ships in the wheel and must not be copied into Lambda zips. Per-function zips should be built with `uv export --no-dev --no-emit-project` for dependencies plus a copy of only the needed packages (or one wheel per function), which also keeps tests and the 51-entry cassette out of the zips. `uv sync` in CI now installs the project editable. The frozen `lock_uv_backend.toml` fixture in `core/graph` is a snapshot and does not change; the live `backend/uv.lock` will list the project as `editable = "."` instead of `virtual = "."`, which `parse_uv_lock` supports. |
| GitHub Action, PR comments, diff of base and head | `vigil-action` | CI gating here is the exit code only. |
| Coroner's Report (Markdown, PDF, VEX) | `coroners-report` | The JSON report is its input, not its replacement. |
| Cause-of-death sentence (AU-6), Séance | `narrate`, `seance` | Bedrock. The CLI's `why` is deterministic and is not a narrative. |
| Themed output, colour, tombstones, Lights On parity | `graveyard-ui` | The CLI is the plain, scriptable surface. |
| Metrics (`ScanDurationSeconds`, `SourceErrors{source}`) and logging | `observability` | `SourceStats` is in the JSON for later use. The CLI emits no metrics and logs nothing. |
| `pnpm-lock.yaml`, `yarn.lock`, `Pipfile.lock` | later ingest spec | P0/P1 in EX-2, but `core.graph` has no parser for them yet. Syft still lists their packages when `--sbom` is used. |
| Parallel Syft runs, per-service timeouts beyond one flag | later, if needed | At most 50 services run in sequence. |

---

## Decisions taken in review

All seven questions raised with the first draft are closed. The IDs stay because requirements above refer to them.

| ID | Question | Decision |
|----|----------|----------|
| Q1 | Packaging for a real `graveyard` command | **Yes.** Pinned `hatchling`, `[tool.uv] package = true`, `[project.scripts] graveyard = "cli.__main__:main"`, wheel packages `core`, `sources`, `cli`, package data including `weights.v1.yaml`. `uv run` keeps working. Lambda impact is in "Belongs elsewhere" (D2, CLI-DEP-3). |
| Q2 | `--fail-on` semantics | **Set membership** (D10). To gate on everything pass `dead,cursed,ailing`. |
| Q3 | Syft failure for one service | **Fatal, exit 3** (D6). |
| Q4 | Command name | **Keep `autopsy`.** Add the single-package mode `--purl` for the install-blocker hook (D19, CLI-PURL-1…6, CLI-TEST-11). PRD, `structure.md` and hook H6 are updated to the name `autopsy` (see "Belongs elsewhere"). |
| Q5 | Default contact | **`https://github.com/olajaido/graveyard`**, as the code constant `DEFAULT_CONTACT` (CLI-ENV-5). |
| Q6 | Default table hides Alive and Resting | **Keep** (D16). |
| Q7 | Degraded gate | **Keep the stderr warning and `summary.degraded`, exit code unchanged, no `--strict` for now** (CLI-GATE-3). |

---

## Review round 2 (real-Syft findings)

The smoke run of 11 Nov 2026 against the real Syft 1.56.0 (T11.3) showed that the hand-written SBOMs of T3 hid three problems. This section records the facts, the decisions and the new requirements. It amends earlier rows where it says so.

### Facts (checked 11 Nov 2026)

| Fact | Evidence |
|---|---|
| By default Syft drops the `dev: true` packages of a `package-lock.json`. With `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true` they appear as components (with their own edges, e.g. `request -> uuid`). | `syft dir:<web>` listed 5 library components; with the variable, 7. |
| Syft never links the project root to its dev direct dependencies (npm `devDependencies`, uv dev groups). | In both real BOMs the root `dependsOn` lists only the runtime directs. `nose` (uv dev group) is a component but has no incoming edge. |
| `core.graph` reads a `dependencies` entry that no other entry lists, has targets and belongs to a component as a **root**. With dev dependencies on, `request` (orphan, with the edge to `uuid`) therefore becomes a second root and is dropped as a package. | `core/graph/cyclonedx.py` root rule; candidate roots of the real flagged BOM: `anchors-web` and `request`. |
| The only absolute path in Syft's output is `metadata.component.name`. | `grep` over both real documents. |
| Without a token, every package that has a repo carries one `GITHUB_DISABLED` warning whose `signals` list the scored signals it could not read; packages with no resolved repo carry no warning, and their missing signals have the note `no GitHub repo resolved`. `SourceWarning.signals` is "the signals that ended up missing because of this failure". | A token-less replay of the nine anchors (warnings and notes printed per package). |
| Live and without a token `six` has only S2, S4, S8 and scores 68.6 (Dead by score); with GitHub data it is Resting. | T11.3 smoke run. |

### Decisions

| ID | Decision | Rationale and consequence |
|----|----------|---------------------------|
| D20 | **Syft runs with `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true`**, set by `syft.py` next to `SYFT_CHECK_FOR_APP_UPDATE=false`. | Without it npm dev packages never reach the graph. Syft reads only files, so the variable does not widen what it touches. |
| D21 | **The CLI adds `root -> direct` edges from the lockfile before building the graph** (`cli/augment.py`). Only edges whose source is the root are added; nothing is removed or changed. | Syft does not link dev directs to the root, so dev packages would otherwise be unreachable (exposure assumed, overstated) or, if they have edges of their own, misread as extra roots. The lockfile is the source of truth for what the project declares (EX-8). |
| D22 | **The gate only counts evidence that was seen.** A package whose verdict rests on the score (Dead by score, or Ailing) while a scored signal is missing because a source was skipped or failed is *unverified* and is not gated. Declared Dead is always gated, and so is Cursed when an advisory meets the age rule on its own; a Cursed that holds only through the Dead/Ailing bypass follows its base state. (Extended in the final round-2 tweaks.) | A score computed from the half of the signals that happened to load is not a verdict. A missing GitHub token must not turn `six` into a blocked install. |
| D23 | **Fixtures are real Syft output**, path-scrubbed, with the provenance recorded, and an opt-in contract test runs the real binary. | The stub BOMs encoded an assumption about Syft (root edges to dev directs) that was false. |
| D24 | **`summary.stats` is the home of CLI-level counters** (`direct_edges_added`, `unverified`). | The review asked for `stats.direct_edges_added`; the report has no top-level `stats`, and `summary.sources` holds the source statistics, so the counters live in a new `summary.stats` object. |

### Dev dependencies and direct edges

| ID | Requirement |
|----|-------------|
| CLI-DEV-1 | `cli/syft.py` SHALL start Syft, for `--version` and for every run, with an environment equal to the caller's mapping plus `SYFT_CHECK_FOR_APP_UPDATE=false` and `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true`. `syft.py` sets both itself, so a caller's mapping cannot leave them out or override them. No other `SYFT_*` variable is set. (Amends CLI-ENV-6.) |
| CLI-DEV-2 | The stub Syft SHALL record the values of every `SYFT_*` variable it sees, for `--version` calls and for run calls, and the tests SHALL assert the two values exactly, including when the caller's mapping tries to set them to something else. |
| CLI-AUG-1 | `cli/augment.py` SHALL be pure (no I/O, no clock, no environment) and provide `add_direct_edges(bom, direct_scopes) -> AugmentResult`, a `NamedTuple` of `(bom, added_keys, missing_keys)`. `bom` is a CycloneDX document as a mapping; `direct_scopes` maps package keys to scopes (the merged `ScopeResult.direct_scopes`). `added_keys` and `missing_keys` are sorted tuples of package keys. It never raises for a document `core.graph` would accept; for a document whose shape it cannot read it returns the input unchanged with no added keys. |
| CLI-AUG-2 | **Root choice.** The candidate roots are the `dependencies` refs that no `dependsOn` lists and that are either the `metadata.component` bom-ref or a component bom-ref with at least one target (the rule `core.graph` uses). Candidates whose package key is itself in `direct_scopes` (orphan dev directs) are not the root. If exactly one candidate remains it is the root. If none remains and `metadata.component` has a bom-ref, that ref is the root and gets a new `dependencies` entry. Otherwise there is no unambiguous root and nothing is added. |
| CLI-AUG-3 | **Adding.** For each key in `direct_scopes`, in sorted order: if a component with that package key exists (smallest bom-ref when several) and the root does not already depend, by package key, on a component with that key, the root gets `dependsOn` that component. New refs are appended to the root's existing `dependsOn` after the original ones. The key is the root itself: skipped. A key with no component that has a bom-ref is a missing key. |
| CLI-AUG-4 | **Safety.** The function SHALL NOT mutate its input, remove or change any component, remove any edge or reorder an existing `dependsOn`. The output MAY share unchanged sub-objects with the input. It is idempotent: applying it to its own output returns an equal document and no added keys. |
| CLI-AUG-5 | Keys in `missing_keys` SHALL produce one `CliWarning` per service with code `DIRECT_NOT_IN_SBOM`, a fixed-template detail that gives the count (`N direct dependencies declared in the lockfile have no component in the SBOM; they are not analysed`), the service, and the sorted keys as `subjects`, capped at 20. The code joins the closed set of CLI warning codes. It does not make the run `degraded` and does not change the exit code. |
| CLI-AUG-6 | Added edges are not warnings. The total over all services SHALL be reported as `summary.stats.direct_edges_added` (D24). |
| CLI-AUG-7 | Augmentation SHALL run in project mode for every service whose lockfiles gave scopes, and in `--sbom` mode when lockfiles were found directly in `PATH`. It SHALL NOT run when there are no scopes, nor in `--purl` mode. It runs before `build_graph`. |
| CLI-AUG-8 | **Tests.** Unit tests on the real fixtures (web: `request` gets a root edge and stops being a second root; api: `nose` is added), on a document with a missing key, a dev-only project (root without a `dependencies` entry, `metadata.component` as root), no root, two roots, a key present twice, a key already linked through another ref, malformed input. Property tests (`@pytest.mark.property`): only root-sourced edges are added; the input is unchanged; idempotent; original edges and components are preserved; every direct key that has a component ends up a root child. |
| CLI-AUG-9 | **Known limits**, stated in the README: a project whose root cannot be identified (several unexplained orphan roots, or no root and no `metadata.component`) is not augmented, and `core.graph` then reports `ROOT_NOT_FOUND` or `MULTIPLE_ROOTS`; packages that are not declared in the lockfile but unreachable (for example a transitive dev dependency whose parent Syft dropped) stay unreachable. |

### Real fixtures and the contract test

| ID | Requirement |
|----|-------------|
| CLI-FIX-1 | `cli/tests/fixtures/sboms/web.cdx.json` and `api.cdx.json` SHALL be the real output of Syft 1.56.0 for the anchors-project services, produced with `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true`, with exactly one edit: `metadata.component.name` (an absolute path) replaced by `fixtures/web` or `fixtures/api` (the method used for the `core/graph` fixtures). `all.cdx.json` is dropped; the tests that used it are rewritten around `web.cdx.json` with the project's `web/` directory (CLI-TEST-4a below). |
| CLI-FIX-2 | `cli/tests/fixtures/anchors-project/README.md` SHALL record the provenance: the Syft version, the exact commands and variables, the date, the single scrub, that nothing else was edited, and why the stub BOMs of T3 were replaced. |
| CLI-FIX-3 | The end-to-end tests SHALL still give the nine states, the design §9.2 `path_infos` and the rank order, now through `augment.py`. If they do not, the task stops and reports. |
| CLI-TEST-13 | **Contract test**, `cli/tests/test_syft_contract.py`, marked `syft`: it runs the real Syft 1.56.0 through `collect_inputs` on the anchors-project and asserts the graph holds the nine anchor packages with the §9.2 `path_infos` after augmentation. It is skipped, with a reason, unless a `syft` binary reporting exactly `1.56.0` is found (`PATH`, then `~/.local/bin/syft`). It reads no network. |
| CLI-TEST-14 | The `syft` marker SHALL be registered in `pyproject.toml` (`--strict-markers` is on). `uv run pytest -m "not syft"` runs everything else. |
| CLI-TEST-4a | **(Replaces the `--sbom` variant of CLI-TEST-4.)** `--sbom web.cdx.json` with `PATH` the project's `web/` directory (it holds a `package-lock.json`): exit 0, `input.mode == "sbom"`, `input.services == ["."]`, the lockfile used, the seven npm packages in the MM-ANC states, `request` with scope `dev`. A second test: `--sbom api.cdx.json` with a `PATH` that has no lockfile gives `SCOPE_ASSUMED`, and `nose` (listed, unreachable) has `exposure_assumed` true. |

### Gate only on evidence that was seen

| ID | Requirement |
|----|-------------|
| CLI-EVID-1 | A package is **gate_eligible** unless its verdict rests on the score **and** at least one scored signal is missing because its source was skipped or failed. *Rests on the score* means: its base state is Dead by score (`dead_reason == "score"`) or Ailing, and it is not Cursed through the age rule (CLI-EVID-3). Otherwise it is eligible. A package that is not gate_eligible is **unverified**. |
| CLI-EVID-2 | **How "skipped or failed" is decided.** A scored signal is missing when its normalised risk in `ScoringResult.normalised_risks` is `None`. It is missing because of a skip or failure when at least one `SourceWarning` of the package lists it in `signals` (`r2` -> `s2_latest_release_at`, `r3` -> `s3_last_push_at`, `r4` -> `s4_maintained`, `r5` -> `s5_committers`, `r6` -> `s6_open_issues` or `s6_closed_issues`, `r8` -> `s8_overall`). A signal that is missing with no such warning (no repository resolved, a 404 or absent record, a field the source does not report) does not count. The sources named by those warnings (`SourceWarning.source`, sorted, unique) are the package's unverified sources. If a future `sources` change stops listing the missing signals in its warnings, the tests of CLI-EVID-9 fail. |
| CLI-EVID-3 | Declared Dead (`dead_reason == "declared"`) is always gate_eligible. The Cursed overlay is gate_eligible when at least one no-fix advisory meets the age rule on its own (published at least the model's `cursed_min_age_days` before `as_of`; an advisory with no publication date never does). That is a fact about the advisory and the date, not about the score. A package that is Cursed **only** through the Dead/Ailing bypass (the model lets a no-fix advisory count when the base state is Dead or Ailing) follows the eligibility of its base state (CLI-EVID-1). Resting, Alive and Unknown are not made ineligible by this rule. To tell the two kinds of Cursed apart the CLI asks `score_package` about the package's advisories alone: with every scored signal absent the base state is Unknown, the bypass cannot apply, and `cursed` is true only through the age rule. No age threshold appears in the CLI (D9). |
| CLI-EVID-4 | `--fail-on` SHALL ignore packages that are not gate_eligible: `Report.matches`, `summary.gate.matches`, the gate message and the exit code count eligible packages only. |
| CLI-EVID-5 | In the table, the `WHY` of an unverified package SHALL start with the short text `unverified: no <source> data` (for example `unverified: no GitHub data`), followed by the usual fragments, so that it fits 100 columns. Source names use their display labels (`GitHub`, `Scorecard`, `deps.dev`, `OSV`, `npm registry`, `PyPI`, ...); several are joined with `, ` and `and` (`no GitHub and Scorecard data`). The state and the priority are shown as before. The JSON `unverified_reason` keeps the long form `<sources> data unavailable` with the raw source names (CLI-EVID-7). |
| CLI-EVID-6 | When at least one package is unverified, the footer SHALL be followed by one line: `N unverified, not gated; set GITHUB_TOKEN to verify` when the run had no usable token, else `N unverified, not gated; rerun when the sources are reachable`. |
| CLI-EVID-7 | The JSON SHALL give each package `gate_eligible` (boolean) and `unverified_reason` (`"<sources> data unavailable"` or `null`), placed directly after `why`, and `summary.stats.unverified` (the count). Adding keys keeps `schema_version` at 1 (D12). |
| CLI-EVID-8 | When `--fail-on` is set and any package is unverified, stderr SHALL say how many packages were not gated (`note: N packages are unverified and were not gated`), in addition to the partial-evidence note of CLI-GATE-3. |
| CLI-EVID-9 | **Tests.** Without a token the anchors project with `--fail-on dead,cursed` exits 1 (declared deaths and `pycrypto` Cursed gate), `six` is unverified and not in `matches`, `nose` (no repo, so nothing was skipped) is gated. `--purl pkg:pypi/six@1.17.0 --fail-on dead,cursed` with no token exits 0 and `six` is unverified. With a token the same `six` run is Resting. Unit tests for the rule on hand-built warnings (each source kind, absent versus failed, declared; Ailing with and without a skipped source; Cursed by the age rule, Cursed only through the bypass on a Dead and on an Ailing package, an advisory with no publication date), and property tests against an oracle written from the `Signals` fields and the model's age threshold: eligibility never depends on a signal that is not missing, declared Dead and Cursed-by-age are always eligible, a package with no warnings is always eligible. |

### Documentation

| ID | Requirement |
|----|-------------|
| CLI-DOC-1 | `docs/adr/0001-data-sources-and-sbom.md` and `docs/SPIKES.md` SHALL record the Syft finding: dev dependencies are dropped by default and dev directs are not linked to the root; the variable that includes them; the CLI's augmentation. |
| CLI-DOC-2 | `.kiro/steering/structure.md` SHALL describe `cli/` as `graveyard CLI (autopsy; later check-install, scan)` and carry the separation rule "`cli/` is glue: no scoring, no parsing, no HTTP; reads the environment only in `__main__.py`". |
| CLI-DOC-3 | `.kiro/steering/testing.md` SHALL list `backend/cli` in the 85 % line-coverage gate. |
| CLI-DOC-4 | `docs/PRD.md` SHALL use the command name `autopsy` (repository structure, hook H6, hook H9's note); H6 becomes `graveyard autopsy . --fail-on dead,cursed`. |

### Amendments to earlier requirements

| Earlier row | Change |
|---|---|
| CLI-ENV-6 | Adds `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true` (CLI-DEV-1). |
| CLI-GATE-1, CLI-GATE-3 | Only gate_eligible packages match (CLI-EVID-4); the partial-evidence note stays. |
| CLI-JSON-3, CLI-JSON-6 | Packages gain `gate_eligible` and `unverified_reason`; `summary` gains `stats` (CLI-EVID-7, CLI-AUG-6). |
| CLI-OUT-4 | `WHY` may start with the `unverified:` fragment (CLI-EVID-5). |
| CLI-OUT-9 | **Amended by kiro-power (KPW-POL-1).** The shrink order is now `EXPOSURE` (down to 12), then `PACKAGE` (down to 20), then `WHY` (down to 8, shortened with `…` last). `STATE` and `PRIORITY` never shrink. |
| CLI-GATE-3 | **Amended by kiro-power (KPW-POL-2).** The partial-evidence note omits the `; N packages Unknown` clause when N is 0 (`note: the gate was evaluated on partial evidence`); it keeps the clause for N ≥ 1. Exit codes and the JSON schema are unchanged. |
| CLI-TEST-2, CLI-TEST-3, CLI-TEST-4 | Real SBOMs (CLI-FIX-1), through `augment.py` (CLI-FIX-3); the `--sbom` variant is CLI-TEST-4a. |
| Warning codes | `DIRECT_NOT_IN_SBOM` joins `LOCKFILE_UNREADABLE`, `GITHUB_TOKEN_MISSING`, `GITHUB_TOKEN_INVALID`. |

### Final round-2 tweaks

| Tweak | Change |
|---|---|
| Shorter `WHY` text | `unverified: no <source> data` instead of `unverified: <sources> data unavailable`, so the reason survives 100 columns (CLI-EVID-5). The JSON `unverified_reason` is unchanged. |
| Wider eligibility | Ailing joins Dead-by-score as a score-based verdict that is not gated when a scored signal was skipped or failed. Cursed stays gated when an advisory meets the age rule on its own; a Cursed that holds only through the Dead/Ailing bypass follows its base state (CLI-EVID-1, CLI-EVID-3, D22). |
| CLI-AUG-9 | Unchanged: the unreadable-lockfile and undeterminable-root cases remain documented limits, not fixed. |

