# Tasks: purl-and-versions

> Implements `.kiro/specs/purl-and-versions/requirements.md` per `.kiro/specs/purl-and-versions/design.md`.
> Each implementation task includes its own unit and property tests as sub-tasks (PV-NFR-5). Tests land immediately after the code they exercise, not at the end.
> All paths are under `backend/core/purl/` unless stated. Tests are colocated in `tests/` and resolve fixtures via `Path(__file__).parent`.
> Run every Python tool from `backend/` via `uv run`. Never call `pytest`, `ruff` or `mypy` bare.
> Already done while writing this spec: the semver / PEP 440 row was removed from PRD §11.6 and from `.kiro/steering/testing.md` (D1).

- [ ] T0 — Add and pin `packageurl-python` (PV-DEP-1, 2, 3)
  - [ ] T0.1 — From `backend/`, run `uv add "packageurl-python==<latest>"` where `<latest>` is the newest release on PyPI at execution time (0.17.6 when the spec was written). If the latest differs from 0.17.6, note it in the task result: the design's probes were made against 0.17.6, and T2 will show whether any pinned behaviour changed.
  - [ ] T0.2 — Confirm `[project].dependencies` in `pyproject.toml` contains `packageurl-python==<version>` (exact `==`, no `>=`, `~=` or `latest`) next to `pyyaml`, and that `uv.lock` changed in the same change. No other dependency (runtime or dev) is added.
  - [ ] T0.3 — Smoke check: `uv run python -c "from packageurl import PackageURL, quote, unquote, normalize_qualifiers, normalize_subpath"` succeeds, and `uv run mypy --strict core` stays clean with no `type: ignore` (the package ships `py.typed`).

- [ ] T1 — Syft check: how does Syft v1.56.0 spell an upper-case npm name? (PV-SYFT-1, 2)
  - [ ] T1.1 — Prerequisites: the pinned Syft at `~/.local/bin/syft` (`syft --version` prints 1.56.0) and network access to the npm registry. If either is missing, stop and ask; do not substitute another Syft version.
  - [ ] T1.2 — Add `JSONStream` to the npm spike fixture's `package.json` in `spikes/fixtures/npm` and regenerate `package-lock.json` with `npm install --package-lock-only --ignore-scripts`. Nothing is installed or executed. Review the lockfile diff: it should add `JSONStream` and its dependencies only; if existing pinned entries change unexpectedly, keep the old entries.
  - [ ] T1.3 — Run `syft dir:spikes/fixtures/npm -o cyclonedx-json` and find the component for `JSONStream`. Record, in a new "Q6 — npm purl case in Syft output" entry in `docs/SPIKES.md`: Syft version, the exact command, the exact `purl` and `bom-ref` emitted, and the observed case (`JSONStream` or `jsonstream`). Keep the entry short and factual, in the style of the existing rows.
  - [ ] T1.4 — Save the `JSONStream` component (or a minimal excerpt with at least `name`, `version`, `purl`, `bom-ref`) as `tests/fixtures/syft_jsonstream.json`. Check that it contains no secrets or absolute local paths.

- [ ] T2 — Package skeleton and library contract test (D3, D4; PV-PURL-5, 7, 8, 11; PV-SYFT-3)
  - [ ] T2.1 — Create `core/purl/__init__.py` (module docstring only for now) and `tests/__init__.py`, matching `core/scoring/tests/__init__.py`.
  - [ ] T2.2 — Write `tests/test_packageurl_contract.py`. Each test asserts a behaviour from design §2 that the wrapper compensates for, against the pinned library:
    - `from_string` and `to_string` lower-case the npm name (`JSONStream` → `jsonstream`); `normalize_purl=False` keeps it;
    - PyPI `.` is not normalised (`zope.interface` stays), and runs of `_` become `--`;
    - `pkg:npm/left-pad@` gives `version=None`;
    - duplicate qualifier keys collapse to the last value;
    - `x%2Fy` decodes to name `x/y` and formats back as `x/y`;
    - `%zz` is kept literally; spaces around segments are stripped; `x@@1` parses with name `x@`;
    - `PKG:` (upper-case scheme) raises `ValueError`; `pkg://npm/x@1` is accepted;
    - `quote` leaves `/` and `:` unencoded and encodes `@`, `+`, `?`, `#`, `%` and non-ASCII;
    - an unpaired surrogate raises a `ValueError` subclass (`UnicodeEncodeError`).
  - [ ] T2.3 — Add the Syft assertions (PV-SYFT-3), reading `tests/fixtures/syft_jsonstream.json`: the emitted purl is quoted in the test as a literal taken from the fixture. Assertions that hold whatever Syft emitted: `PackageURL.from_string` accepts it; `registry_name`-equivalent name is `JSONStream` (taken from the component's `name`); the lower-cased spelling of the emitted purl gives the same dedupe identity. The assertions on `parse_purl`, `package_key` and `registry_name` are added in T4.4 and T5.2 once those functions exist; leave a `# TODO(T4.4, T5.2)` marker only if it is removed in those tasks.
  - [ ] T2.4 — `uv run pytest core/purl -q` passes. A failing contract test after a future library upgrade is the intended signal to simplify the wrapper; add that note to the module docstring.

- [ ] T3 — `model.py`: `Purl`, constants, validation + strategies + tests (PV-PURL-2, 3, 5, 7, 8, 9, 11; PV-NFR-1)
  - [ ] T3.1 — Implement `model.py` with `Ecosystem`, the frozen `Purl` dataclass, the constants from design §3 (`MAX_INPUT_LEN`, `SUPPORTED`, the compiled regexes), `normalise_pypi_name`, and `_ascii_lower`. `Purl.__post_init__` implements the validation table in design §4.1 and raises `ValueError` with a message that names the rule and quotes the offending value via `repr()` truncated to 100 characters. No I/O, clock or environment access.
  - [ ] T3.2 — Create `tests/strategies.py` with the valid-domain building blocks: `npm_scopes()`, `npm_names()`, `pypi_names()`, `versions()`, `qualifiers()`, `subpaths()`, `purls()` and `ascii_case_flip()`. Build values constructively; use `.filter` only for cheap rejections so the `ci` profile does not trip Hypothesis health checks. Include `?#%+:`, `@` in versions and qualifier values, interior spaces in qualifier values and subpath segments only, and non-ASCII characters.
  - [ ] T3.3 — Write `tests/test_model.py` unit tests: each valid shape constructs (unscoped npm, scoped npm, pypi, no version, qualifiers, subpath); each invalid shape raises `ValueError` (unsupported ecosystem, npm namespace without `@`, `@` alone, scope containing `@` or `/`, pypi with namespace, empty name, name containing `/`, npm name containing `@`, pypi name not PEP 503-normalised, empty-string version, whitespace or control characters, non-canonical qualifiers: unsorted, duplicate, upper-case key, empty value, padded value, and bad subpath segments `.`, `..`, empty). Also `normalise_pypi_name` examples and `_ascii_lower` (including that U+212A is left alone).
  - [ ] T3.4 — Property tests (`@pytest.mark.property`) in `tests/test_model_properties.py`: every `purls()` value constructs and is a fixed point of validation (`test_purl_values_valid`); mutated field values (flip one field to an invalid value) raise `ValueError` and nothing else (`test_purl_invalid_fields_raise_value_error`); `test_pep503_idempotent` and `test_pep503_variants_collapse` (PV-INV-5, name part only).

- [ ] T4 — `purl.py`: `parse_purl`, `format_purl`, `normalise_purl` + tests (PV-PURL-1…13; PV-INV-1…6)
  - [ ] T4.1 — Implement `parse_purl` per design §4.2: input guards (type, length, whitespace and control characters, malformed `%`, empty version after `@`, duplicate qualifier keys) before any library call; library parse in one `try` (normalised and raw); ecosystem allow-list; npm case recovered from the raw parse; PEP 503 for pypi; construct `Purl`. Only `ValueError` escapes; other exceptions are chained with `raise … from exc`. Implement `format_purl` per design §4.3 (library `quote`, `normalize_qualifiers`, `normalize_subpath`; never `to_string()`) and `normalise_purl`.
  - [ ] T4.2 — Extend `tests/strategies.py` with `purl_strings()` (non-canonical renderings plus an expected canonical string built independently with `urllib.parse.quote(…, safe="/:")` and a test-local PEP 503) and `invalid_purl_strings()` (arbitrary `text()` including surrogates and >2,048 characters; mutations of valid purls; disallowed types).
  - [ ] T4.3 — Write `tests/test_purl.py` unit tests from the requirements' purl table (`normalise_purl` column) and the `ValueError` list, plus: npm case preserved; scope written `%40scope`; `pkg://` accepted; qualifiers and subpath canonicalised; 2,048-character boundary (2,048 accepted if otherwise valid, 2,049 rejected) and that the library is not called above the cap (patch `PackageURL.from_string` to fail if called); a non-`str` argument raises `ValueError`; library exceptions are wrapped and chained (patch the library to raise `RuntimeError`).
  - [ ] T4.4 — Add the `parse_purl` side of the Syft assertions to `tests/test_packageurl_contract.py` (PV-SYFT-3): the emitted `JSONStream` purl parses, keeps its case in `name`, and `normalise_purl` of it equals `normalise_purl` of the same purl rewritten with the `%40`/case variants the test can derive. Remove the T2.3 marker if one was added.
  - [ ] T4.5 — Property tests (`@pytest.mark.property`) in `tests/test_purl_properties.py`:
    - PV-INV-1 `test_purl_round_trip`, `test_purl_matches_oracle`, `test_purl_value_round_trip`;
    - PV-INV-2 `test_normalise_purl_idempotent`;
    - PV-INV-3 `test_parse_valid_never_raises`;
    - PV-INV-4 `test_parse_only_raises_value_error`, `test_parse_rejects_other_ecosystems`;
    - PV-INV-6 `test_npm_case_preserved`.
    If a property fails, fix the code (or the oracle, when the oracle is wrong), and record the counterexample in `docs/KIRO_JOURNAL.md`. This is the "bug PBT found" for the write-up.

- [ ] T5 — `package_key` and `registry_name` + tests (PV-KEY-1…4, PV-REG-1, 2; PV-INV-7, 8, 14)
  - [ ] T5.1 — Implement `package_key` per design §4.4 (strip qualifiers and subpath; for npm ASCII-lower-case namespace and name; keep the version as is; `format_purl(k).removeprefix("pkg:")`) with a docstring that states its use for EX-7 and AU-5 and that it must not be used where the registry name is needed (PV-KEY-2). Implement `registry_name` (decoded, not URL-encoded, case preserved).
  - [ ] T5.2 — Write `tests/test_key.py` unit tests from the purl table's `package_key` and `registry_name` columns, including `JSONStream` → `npm/jsonstream@1.3.5` with `registry_name` `JSONStream`, `@Babel/Core` → `npm/%40babel/core@7.24.0`, a version containing upper-case letters left alone, a non-ASCII npm name left alone, no version, and pypi unchanged. Add the `package_key` and `registry_name` side of the Syft assertions (PV-SYFT-3): the Syft-emitted `JSONStream` purl and its lower-case spelling have the same `package_key`, and `registry_name` is `JSONStream`.
  - [ ] T5.3 — Property tests (`@pytest.mark.property`) in `tests/test_purl_properties.py`:
    - PV-INV-7 `test_package_key_ignores_qualifiers_subpath`, `test_package_key_idempotent_under_normalise`, `test_package_key_reversible` (expected value built in the test, not via `package_key`), `test_package_key_stable_under_rekey`;
    - PV-INV-8 `test_registry_name_round_trip`, `test_registry_name_npm_shape`;
    - PV-INV-14 `test_package_key_npm_case_insensitive`, `test_package_key_npm_version_and_non_ascii_not_folded`, `test_package_key_keeps_case_in_other_outputs`, `test_package_key_pypi_unchanged`.

- [ ] T6 — `repo_url.py`: `normalise_repo_url` + fixtures + tests (PV-REPO-1…12; PV-INV-9…12)
  - [ ] T6.1 — Implement `normalise_repo_url` per design §5.2 without `urllib.parse`: guards (type, whitespace-strip, length, whitespace and control characters, backslash, `%2e`/`%2f`/`%5c`), fragment then query cut, form detection (URL schemes, scp-like `git@host:`, `github:`, scheme-less), authority checks (userinfo exactly `git`, no port, ASCII host in `{github.com, www.github.com}`), segment checks, repeated `.git` strip, charset check. Return `None` on any doubt; wrap the body in `try/except Exception` returning `None`. `git@www.github.com:…` is rejected.
  - [ ] T6.2 — Create `tests/fixtures/real_repo_urls.json` with the six real inputs from the requirements (`input`, `expected`, `source`). Take the `PyPI` and `deps.dev` values from `spikes/out_pypi.json` and `spikes/out_depsdev.json`; label the two npm `repository` values `registry repository field` as in the requirements.
  - [ ] T6.3 — Write `tests/test_repo_url.py`: parametrised over the real fixture file and the synthetic table; each accepted-form row; `www.github.com`; `git@www.github.com:o/r` is `None`; repeated `.git`; scheme and `github:` prefix case-insensitive; owner and repo case preserved; non-`str` input returns `None`; 2,048/2,049-character boundary; and a cross-check that the `request`, `node-uuid` and `six` entries agree with the `repo` field in `core/scoring/tests/fixtures/anchors/*.json`.
  - [ ] T6.4 — Extend `tests/strategies.py` with `repo_urls()` (returns `(url, owner, repo)`) and `adversarial_repo_urls()` covering every family in PV-INV-11.
  - [ ] T6.5 — Property tests (`@pytest.mark.property`) in `tests/test_repo_url_properties.py`:
    - PV-INV-9 `test_repo_normaliser_idempotent`;
    - PV-INV-10 `test_repo_output_shape`, `test_repo_never_raises`;
    - PV-INV-11 `test_repo_adversarial_never_github`;
    - PV-INV-12 `test_repo_accepted_forms_exact`.
    Run the adversarial test at least once with `HYPOTHESIS_PROFILE=ci` before closing the task; record any counterexample in `docs/KIRO_JOURNAL.md`.

- [ ] T7 — `repo_key` + tests (PV-RKEY-1, 2; PV-INV-13)
  - [ ] T7.1 — Implement `repo_key` in `repo_url.py` per design §5.3: `ValueError` unless `REPO_OUT.fullmatch(repo)`, else `repo.lower()`.
  - [ ] T7.2 — Add unit tests to `tests/test_repo_url.py`: the synthetic table's `repo_key` column; `repo_key("https://github.com/o/r")` and `repo_key("github.com/o")` raise `ValueError`; a non-`str` argument raises `ValueError`.
  - [ ] T7.3 — Property tests (`@pytest.mark.property`) in `tests/test_repo_url_properties.py`: PV-INV-13 `test_repo_key_idempotent`, `test_repo_key_case_insensitive` (including the lower-case output pattern and equal keys for URLs differing only in owner or repo case).

- [ ] T8 — Public API in `__init__.py` + API tests (PV-KEY-2; design §1, §3)
  - [ ] T8.1 — Re-export from `core.purl`: `Ecosystem`, `Purl`, `parse_purl`, `format_purl`, `normalise_purl`, `normalise_pypi_name`, `package_key`, `registry_name`, `normalise_repo_url`, `repo_key`, with an explicit `__all__`. The module docstring explains `package_key` (EX-7, AU-5) versus `registry_name` versus `format_purl`, and `repo_key` versus the display form.
  - [ ] T8.2 — Write `tests/test_public_api.py`: `__all__` equals the expected set; every name is importable from `core.purl`; `core.purl` does not import `core.scoring` and has no I/O imports (`socket`, `urllib.request`, `http`, `subprocess`, `os.environ`/`os.getenv` use) — check by inspecting the modules' imports with `ast` (PV-NFR-1).

- [ ] T9 — Final gate (PV-DEP-1…3, PV-NFR-1…5). Run from `backend/`; fix and re-run until all pass.
  - [ ] T9.1 — `uv run ruff check` and `uv run ruff format --check` are clean.
  - [ ] T9.2 — `uv run mypy --strict core` is clean, and `grep -rn "type: ignore" core/purl` finds nothing.
  - [ ] T9.3 — `uv run pytest -q` is green, including the contract tests and the existing `core/scoring` tests.
  - [ ] T9.4 — `HYPOTHESIS_PROFILE=ci uv run pytest -m property -q` is green (`max_examples=500`).
  - [ ] T9.5 — Coverage: `uv run pytest core/purl --cov=core/purl --cov-report=term-missing --cov-fail-under=85` passes. Report the actual percentage. The `except Exception` fallbacks in `normalise_repo_url` and `parse_purl` may legitimately show as uncovered unless a test forces them (T4.3 forces the parse one).
  - [ ] T9.6 — Dependency check: `git diff --stat backend/pyproject.toml backend/uv.lock` shows only the `packageurl-python==<version>` addition (plus its lock entry); no other runtime dependency was added (PV-DEP-3).
  - [ ] T9.7 — Traceability check: confirm every PV-INV-1…14 test name in the requirements exists in `tests/`, and every PV-* requirement ID appears in at least one test docstring or the design's traceability table. Report any gap instead of closing silently.
