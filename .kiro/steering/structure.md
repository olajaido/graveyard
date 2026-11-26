---
inclusion: always
---

# Repo Structure Steering — Graveyard

## Layout

```
graveyard/
├── .kiro/
│   ├── specs/<feature>/{requirements,design,tasks}.md
│   ├── steering/*.md
│   ├── hooks/*.json
│   ├── agents/*.json
│   ├── skills/                  # copies of powers/graveyard/skills (written by scripts/hooks/sync-power.py)
│   └── settings/mcp.json
├── powers/graveyard/            # Kiro Power (Agent Plugins): plugin.json, mcp.json, skills/ (incl. hook template); source of the .kiro copies
├── backend/
│   ├── pyproject.toml          # uv-managed; Python 3.12; pytest, ruff, mypy config
│   ├── core/                    # pure logic: purl, versions, scoring, graph, sources, scan (PBT heavy)
│   │   ├── scoring/tests/       # colocated tests + fixtures/anchors/ for the scoring core
│   │   ├── bands.py             # pure: confidence band constants (none, low, medium, full); no import from core.scoring
│   │   ├── scan/                # pure: scan IDs, error codes, record and cursor builders (no I/O)
│   │   ├── install/             # pure: install-command parser and hook payload extractor (no I/O)
│   │   └── sources/             # pure half of the source clients: parsers, has_fix, repo resolution, signal assembly
│   │       └── tests/fixtures/recorded/   # recorded HTTP cassette shared with backend/sources/tests
│   ├── exhume/                  # GitHub side of a scan: repo validation, tree selection, Reader app JWT and token, trees and blobs (httpx client passed in)
│   ├── scan/                    # table and artefacts bucket (Protocols + boto3 adapters, clients passed in), SSM limits
│   ├── sources/                 # I/O half of the source clients: async gateway, per-source clients, cache, session (imports core.sources)
│   ├── workflow/                # Step Functions task handlers
│   ├── api/                     # handlers + openapi.yaml
│   ├── rites/                   # reincarnate, seal, necromancy; codemod rules
│   ├── narrate/                 # Bedrock prompts + validators
│   ├── eval/                    # eval harness code (not shipped); colocated tests in eval/tests/; data lives in repo-root eval/
│   ├── mcp_server/              # graveyard-mcp server (not mcp/: it would shadow the SDK)
│   ├── cli/                     # graveyard CLI (autopsy, check-install; later scan); may import core.install
│   └── tests/{unit,property,integration,fixtures}
├── web/                         # Next.js app
├── infra/
│   ├── .tool-versions           # pinned Terraform, tflint, checkov, actionlint versions
│   ├── .tflint.hcl
│   ├── modules/{state,github-oidc,cost,data,github-app,lambda-function,workflow,api,observability,edge-cert,edge-waf,edge-site,edge-api,edge-alarms,web,ai}
│   ├── envs/{dev,prod}/         # thin roots: backend config, tfvars, module calls
│   └── bootstrap/               # state bucket, OIDC roles, budget; applied locally by a maintainer once
├── actions/vigil/               # GitHub Action
├── eval/                        # data only: labelled set, fixtures, staging, gate.yaml, LABELLING.md, README.md, results.json
├── docs/{PRD.md,KIRO_JOURNAL.md,ARCHITECTURE.md,runbooks/}
├── scripts/hooks/               # incl. sync-power.py (writes the .kiro copies of the Power; --check mode)
├── scripts/build/               # deterministic lambda.zip and syft-layer.zip builders, syft-pin.json (SHA-256 pin); stdlib tests
├── scripts/ci/                  # local-checks.sh (pinned images), guards, changed_paths, tests/
├── .github/workflows/{ci.yml,deploy.yml,vigil.yml}
├── .github/actions/{terraform-init,terraform-plan,terraform-apply,deploy-site}/
├── LICENSE (Apache-2.0)  NOTICE  README.md  SECURITY.md
```

## Naming Conventions

- Directories: lowercase, hyphen-separated (`death-certificate`, not `DeathCertificate`).
- Python modules: snake_case. Classes: PascalCase.
- TypeScript/React: kebab-case file names for components, PascalCase for component names.
- Spec directories: kebab-case, matching the spec name from the PRD spec table.
- Terraform modules: one resource family per module; module name = directory name (hyphenated, e.g. `github-oidc`); resource labels inside may be snake_case.
- Infrastructure env roots: `envs/dev/` and `envs/prod/` only.
- Hooks: `.kiro/hooks/<name>.json` using kebab-case.
- Agents: `.kiro/agents/<name>.json` using lowercase.
- Runbooks: `docs/runbooks/<topic>.md` using kebab-case.

## Separation Rules

- `backend/core/` contains only pure logic with no I/O. Every function here is property-testable.
- Tests for `backend/core/scoring/` are colocated in `backend/core/scoring/tests/`, with fixtures in `backend/core/scoring/tests/fixtures/`. Tests resolve fixture paths via `Path(__file__).parent`, never the working directory. `backend/tests/` remains for cross-package unit, property, and integration tests.
- `backend/core/sources/` is the pure half of the source clients: URL builders, response parsers, `has_fix`, repo resolution, signal assembly, config and result types. It has no I/O and no `httpx`, `asyncio`, `os`, `logging` or `print`. It may import `core.purl` and `core.scoring`, and the only module that may import `core.scoring` beyond `core.scoring.types` is `core/sources/resting.py` (it decides which packages could be Resting, by calling `score_package`). Its tests and the recorded HTTP cassette are colocated in `core/sources/tests/`.
- `backend/sources/` contains only external API clients and caching: the async HTTP gateway, per-source clients, the cache protocol and in-memory cache, and the session. It imports `core.sources` and, from `core.scoring`, only the data-type module `core.scoring.types` (any other `core.scoring` module, and the package itself, is forbidden; tests excepted). No scoring logic, no response parsing rules. Its tests may read the cassette in `core/sources/tests/fixtures/recorded/` through a path relative to `__file__`.
- Neither `core/sources` nor `sources` reads environment variables, logs or prints. Secrets, contact strings and tokens are passed in by the caller (`workflow/` or a script).
- `backend/cli/` is glue: no scoring, no parsing, no HTTP. It calls `core.graph`, `sources` and `core.scoring` (only `score_package`, `sort_results` and the result types), formats the results, and runs Syft through one module (`syft.py`, the only user of `subprocess`). It reads the environment only in `__main__.py` and imports no HTTP client. Its tests and fixtures are colocated in `cli/tests/`.
- `backend/workflow/` contains Step Functions task handlers only. `workflow/runtime.py` and `api/runtime.py` are the only files that read environment variables and build boto3 clients (names only, never a secret).
- `backend/core/scan/` is pure: IDs, error codes, record and cursor builders. `backend/exhume/` and `backend/scan/` take their clients as arguments and read no environment variable.
- `backend/rites/` contains remediation generators and codemod rules. No scoring.
- `backend/narrate/` contains Bedrock prompts and validators only.
- `infra/modules/` contains reusable Terraform modules. No environment-specific values, no data sources (roots pass values in), and policies are built with `jsonencode` in `locals`.
- `infra/bootstrap/` is applied locally by a maintainer once; CI never applies it.
- `infra/envs/` contains thin roots that call modules with tfvars. No resource definitions here.
- `backend/eval/` may import `core`, `cli.gate` and `sources` types. Nothing imports it. The repo-root `eval/` folder holds data only.

## Commit Hygiene

- `.kiro/` must be committed at repo root and never added to `.gitignore`.
- CI must fail if `.kiro` is in `.gitignore`.
- All code written on or after 30 Oct 2026. Pre-existing work disclosed in README "Third-party components".
