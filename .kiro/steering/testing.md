---
inclusion: fileMatch
fileMatchPattern: "**/tests/**"
---

# Testing Steering — Graveyard

## Property-Based Testing (PBT-first for pure functions)

- Use Hypothesis (Python) and fast-check (TypeScript).
- Tag Python tests `@pytest.mark.property`.
- `max_examples=500` in CI (200 locally via hook).
- Capture any bug PBT found for the write-up.

### Required Properties

| Target | Properties |
|---|---|
| purl parse/format | Round-trip `format(parse(s)) == normalise(s)`; parse never raises on valid grammar; rejects invalid |
| Mortality score | Bounds [0,100]; monotonicity (increasing staleness never decreases mortality); declared-dead override; total classification |
| Graph builder | Every path starts at root and ends at node; no cycles in output paths; dedupe is idempotent |
| CycloneDX ingest | Output independent of input order; dedupe is idempotent (`dependency-graph`). The "ingest → export → ingest is a fixed point" property belongs to `coroners-report`, which owns export |
| Codemods | Rewritten file parses; applying twice = applying once (idempotence) |
| check-install parser | Every generated `npm/pnpm/yarn/pip/uv` command variant yields the correct package set |

Semver/PEP 440 range matching has no required properties: OSV `querybatch` matches versions server-side, so there is no in-house matcher (`.kiro/specs/purl-and-versions/requirements.md`, D1).

### Mortality Invariants (§7.7, always hold)

- 0 ≤ mortality ≤ 100 for every input.
- Monotonicity: increasing any staleness input never decreases mortality.
- Declared dead → state is Dead, whatever the other signals are.
- Adding a missing signal never changes confidence in the wrong direction.
- Classification is total: every input maps to exactly one base state.

## Test Layers and Gates

| Layer | Tooling | Gate |
|---|---|---|
| Lint/format | Ruff, mypy (strict on `core`), ESLint, Prettier, tflint, terraform fmt, hadolint, actionlint | CI fail |
| Unit | pytest, Vitest | 85% line coverage on `backend/core` (incl. `backend/core/install`), `backend/rites`, `backend/cli`, `backend/mcp_server` |
| Property | Hypothesis, fast-check | `max_examples=500` in CI |
| Integration | pytest with recorded HTTP fixtures (VCR-style) for every source; LocalStack optional | CI fail |
| Contract | Schemathesis against `openapi.yaml` on dev stage | Deploy gate |
| E2E | Playwright: landing → demo scan → certificate → rite preview; axe-core accessibility | Deploy gate |
| Security | gitleaks, checkov, `pip-audit`/`pnpm audit`, Graveyard Vigil (dog-food), CodeQL | CI fail on high |
| Eval | `make eval` precision ≥ 0.90 | CI fail |
| Load | k6, 20 concurrent scans of demo repo | Manual, W4 |

## Fixture Strategy

- Recorded HTTP fixtures (VCR-style) for every external source.
- Red-team fixtures: poisoned READMEs/issues for narrate and Séance prompt-injection tests.
- Eval set in `eval/labelled_packages.csv`: ~100 packages hand-labelled (dead, finished-healthy, alive, ailing).
- Confusion matrix printed by `make eval`.

## CI/CD Pipeline

```
PR:    lint ─┬─ unit+property ─┬─ integration ─┬─ build (web, lambdas, syft image) ─ tf plan (dev+prod, PR comment)
             └─ security scans ┘               └─ eval
main:  [all of the above] → apply dev → contract + e2e on dev → manual approval (prod) → apply prod → smoke test → alias shift
```

- Jobs run in parallel wherever there is no dependency.
- AWS access via OIDC: plan role (read-only) and apply role restricted to `main` and `prod` environment.
- Caching: pnpm store, uv cache, Docker layer cache (`cache-from: type=gha`), Terraform plugin cache.
