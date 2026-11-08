# Tasks: mortality-model

> Implements `.kiro/specs/mortality-model/requirements.md` per `.kiro/specs/mortality-model/design.md`.
> Each implementation task includes its own tests as sub-tasks. Property tests land immediately after the code they exercise (`score.py`, `classify.py`), not at the end.
> All paths are under `backend/core/scoring/` unless stated. Tests are colocated in `tests/`.

- [x] T0 — Scaffold `backend/` (D1)
  - [x] T0.1 — Create `backend/pyproject.toml` managed by uv: `requires-python = "==3.12.*"`; exact-pinned `pyyaml` and dev group `pytest`, `hypothesis`, `ruff`, `mypy`; commit `uv.lock`. No `latest` or open ranges.
  - [x] T0.2 — pytest config: `--strict-markers`, registered `property` marker, `testpaths = ["core"]`.
  - [x] T0.3 — Create `backend/conftest.py` registering Hypothesis profiles `ci` (`max_examples=500`) and `dev` (`max_examples=200`), selected by `HYPOTHESIS_PROFILE` (default `dev`; unknown name fails loudly).
  - [x] T0.4 — Configure ruff and `mypy --strict` for `backend/core`.
  - [x] T0.5 — Smoke check: `uv run pytest`, `uv run ruff check`, `uv run mypy --strict core` all run clean on the empty package.

- [x] T1 — Model parameters and formula constants
  - [x] T1.1 — Create `weights.v1.yaml` with every key in MM-WGT-2, including the `exposure` block (`runtime`, `dev`, `direct`, `transitive`, `base`) and `cursed_priority_multiplier`. Values are those in the steering file.
  - [x] T1.2 — Create `constants.py` with `R5_BUCKETS` and `R6_MIDPOINT`; docstring states they define formula shape, not tunable parameters.
  - [x] T1.3 — Write `tests/test_constants.py`: bucket values, `R6_MIDPOINT`, and that `weights.v1.yaml` does not duplicate them.

- [x] T2 — `types.py` + tests (MM-VAL-1, D5)
  - [x] T2.1 — Implement `BaseState`, `DeadReason`, `Advisory`, `PathInfo`, `Signals` (date fields `s2_latest_release_at` / `s3_last_push_at`; `s7_advisories` and `paths` as `tuple[..., ...] | None`; `__post_init__` validation), `ScoringResult` (`dead_reason`, `contributions`, `exposure_assumed`), `Weights` (`weights` as read-only mapping).
  - [x] T2.2 — Write `tests/test_types.py` unit tests: each valid boundary constructs (0, 10, -1); each invalid value raises `ValueError` (negative counts, 10.1, -2, -0.5).
  - [x] T2.3 — Property tests (`@pytest.mark.property`): valid-domain strategy constructs (`test_signals_valid_domain`); invalid-domain strategy raises (`test_signals_invalid_domain_raises`).

- [x] T3 — `weights.py` + tests (MM-WGT-1…5, D4, D7)
  - [x] T3.1 — Implement `load_weights(path=None)` resolving the path then delegating to `_load_weights_cached` (`functools.lru_cache`, keyed by resolved path). Use `yaml.safe_load` only. Wrap `weights` in `MappingProxyType`.
  - [x] T3.2 — Validate MM-WGT-2 required keys (missing → `ValueError`) and MM-WGT-5 constraints: `span_months > 0`; `grace_months ≥ 0`; every weight > 0; `0 ≤ ailing < dead ≤ s1_min_score ≤ 100`; `0 ≤ thresholds.resting_r6_max ≤ 1`; `resting_min_weekly_downloads ≥ 0`; `cursed_min_age_days ≥ 0`; `exposure.runtime/dev/direct/transitive` each in `(0, 1]`; `exposure.base` in `[0, 1]`; `cursed_priority_multiplier > 0`.
  - [x] T3.3 — Write `tests/test_weights.py`: shipped YAML loads and stamps `model_version`; each missing key raises; each MM-WGT-5 violation raises (including multiplier `> 1`, multiplier `0`, `base < 0`, `base > 1`); repeated calls and equivalent path spellings return the same cached object; failures are not cached; cached `weights` mapping is read-only; a `cache_clear()` fixture wraps tests that write temporary YAML.

- [x] T4 — `normalise.py` + tests (MM-NOR-1…8)
  - [x] T4.1 — Implement `months_between(start, as_of)` = `(as_of − start).days / 30.4375` and `normalise_signals(signals, w)`. r2/r3 via `months_between`; r5 via `R5_BUCKETS`; r6 via `R6_MIDPOINT`; S4/S8 `-1` → `None`.
  - [x] T4.2 — Write `tests/test_normalise.py` unit tests: each of r2–r8 for present, `None`, `-1`; grace/span boundaries; committers 0–5; 0/0 issues; `None` is never coerced to 0.
  - [x] T4.3 — Property tests: `months_between` non-negative for `start ≤ as_of` (`test_months_between_nonneg`); monotone in `as_of` (`test_months_between_monotone`); every present `rᵢ` lies in `[0, 1]`.

- [x] T5 — `score.py` + tests + property tests (MM-SCO-1…7, MM-INV-1, 2, 4)
  - [x] T5.1 — Implement `compute_mortality`, `compute_contributions`, `apply_s1_override`, `compute_confidence(risks, s1, w)`. S1 override applies even with no scored signals (mortality = `s1_min_score`, confidence 0).
  - [x] T5.2 — Write `tests/test_score.py` unit tests: all/some/none present; S1 override with and without scored signals; confidence range and full set; S1-only confidence 0; `contributions` keys and `None` for absent signals; no rounding.
  - [x] T5.3 — Write `tests/test_properties_score.py` (`@pytest.mark.property`), built from `normalise_signals` + score functions:
    - MM-INV-1 `test_mortality_range`;
    - MM-INV-2 `test_monotonicity_release`, `_push`, `_maintained`, `_overall`, `_committers`, `_open_issues` (closed fixed);
    - MM-INV-4 `test_confidence_range`, `_monotone`, `_full`, `_s1_only`;
    - MM-SCO-7 `test_contributions_sum` using `math.isclose(..., rel_tol=1e-9)` (D6).

- [ ] T6 — `classify.py` + tests + property tests (MM-STA-1…5, MM-OVL-1…3, MM-INV-3, 5, 8)
  - [~] T6.1 — Implement `classify_state(...) -> tuple[BaseState, DeadReason]`, `compute_cursed`, `compute_wounded`. Resting requires `s7_advisories` not `None` and empty. A `published_at` of `None` never satisfies the Cursed age condition. `advisories` parameters are `tuple[Advisory, ...] | None`.
  - [~] T6.2 — Write `tests/test_classify.py` unit tests: each base state; evaluation order; `dead_reason` (`declared` / `score` / `None`); Resting (known-empty advisories, `None` advisories → Ailing, r6 ceiling, downloads known and ≥ minimum); Cursed (age met, age not met, `published_at None`, Dead/Ailing bypass); Wounded (fix, fix-pending, S1b); both overlays together.
  - [~] T6.3 — Write `tests/test_properties_classify.py` (`@pytest.mark.property`): MM-INV-3 `test_s1_implies_dead` (including all-`None` scored signals), MM-INV-5 `test_totality`, MM-INV-8 `test_s1b_not_s1`.

- [ ] T7 — `priority.py` + tests (MM-PRI-1…4)
  - [~] T7.1 — Implement `compute_exposure(paths, w) -> tuple[float, bool]` (default `(1.0, True)` for `None`/empty) and `compute_priority(mortality, exposure, cursed, w)`. All multipliers come from `Weights`; `paths` is `tuple[PathInfo, ...] | None`.
  - [~] T7.2 — Write `tests/test_priority.py` unit tests: `path_weight` for each runtime/direct combination; max over paths; default exposure and `exposure_assumed`; exposure computed for Unknown; priority formula with YAML base and cursed multiplier; priority `None` only when mortality is `None`.

- [ ] T8 — `sort.py` + tests (MM-SRT-1, 2, MM-INV-7)
  - [~] T8.1 — Implement `sort_results(results)`: duplicate purls raise `ValueError`; scored by priority desc → services desc → purl asc; Unknown after scored by exposure desc → services desc (`None` last) → purl asc.
  - [~] T8.2 — Write `tests/test_sort.py` unit tests: each tie-breaker; Unknown ordering including `None` services; duplicate purl rejected.
  - [~] T8.3 — Property tests: MM-INV-7 `test_exposure_always_float`, `test_priority_nonneg`, `test_sort_strict_total_order`.

- [ ] T9 — `__init__.py` pipeline + tests (MM-WGT-3, MM-SCO-5, MM-INV-6)
  - [~] T9.1 — Implement `score_package(signals, weights=None) -> ScoringResult` wiring: normalise → mortality + contributions → S1 override → confidence → classify → overlays → exposure → priority. Re-export `sort_results`.
  - [~] T9.2 — Write `tests/test_pipeline.py`: result stamped with `model_version`; every `ScoringResult` field populated as specified; S1-only and all-`None` inputs.
  - [~] T9.3 — Property test: MM-INV-6 `test_determinism`; re-run MM-INV-1, 3, 5 end to end through `score_package`.

- [ ] T10 — **MANUAL (maintainer runs this; the agent must not)** — `scripts/capture_anchors.py` (D8)
  - [~] T10.1 — Implement the script with PEP 723 inline dependencies, runnable via `uv run`. It reads `GITHUB_TOKEN` from the environment and exits with a clear message if unset. The token is never printed, logged, written to a fixture, or included in an exception message.
  - [~] T10.2 — For each of request, node-uuid, left-pad, express, uuid, moment, pycrypto, nose, six, write `tests/fixtures/anchors/<package>.json` containing `as_of = "2026-11-03"`, every raw signal value, and the source URL for each signal.
  - [~] T10.3 — Maintainer runs it once and commits the fixtures after reviewing them for secrets.

- [ ] T11 — `tests/test_anchors.py` (MM-ANC-1…9) — **depends on T10 output**
  - [~] T11.1 — Resolve fixtures via `Path(__file__).parent / "fixtures" / "anchors"`; no network, no working-directory dependence.
  - [~] T11.2 — Implement `signals_from_fixture` (building tuples for `s7_advisories` / `paths`) and one test per package with the expected states from requirements.
  - [~] T11.3 — `six`: assert the state computed from the fixture and record its mortality as a "borderline sentinel"; Resting only if `r6 ≤ thresholds.resting_r6_max`.

- [ ] T12 — Final gate
  - [~] T12.1 — `uv run ruff check` and `uv run ruff format --check` clean.
  - [~] T12.2 — `uv run mypy --strict core` clean.
  - [~] T12.3 — `HYPOTHESIS_PROFILE=ci uv run pytest` green (`max_examples=500`), including `-m property` and `test_anchors.py`.
  - [~] T12.4 — Confirm 85% line coverage on `backend/core/scoring` (testing.md gate).
