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
│   └── settings/mcp.json
├── powers/graveyard/            # Kiro Power: POWER.md, mcp.json, steering/, hooks
├── backend/
│   ├── pyproject.toml          # uv-managed; Python 3.12; pytest, ruff, mypy config
│   ├── core/                    # pure logic: purl, versions, scoring, graph (PBT heavy)
│   │   └── scoring/tests/       # colocated tests + fixtures/anchors/ for the scoring core
│   ├── sources/                 # osv, depsdev, scorecard, npm, pypi, github clients
│   ├── workflow/                # Step Functions task handlers
│   ├── api/                     # handlers + openapi.yaml
│   ├── rites/                   # reincarnate, seal, necromancy; codemod rules
│   ├── narrate/                 # Bedrock prompts + validators
│   ├── mcp/                     # graveyard-mcp server
│   ├── cli/                     # graveyard CLI (check, check-install, scan)
│   └── tests/{unit,property,integration,fixtures}
├── web/                         # Next.js app
├── infra/
│   ├── modules/{web,api,workflow,data,ai,github_app,observability}
│   ├── envs/{dev,prod}/         # thin roots: backend config, tfvars, module calls
│   └── bootstrap/               # state bucket (S3 native locking), OIDC role
├── actions/vigil/               # GitHub Action
├── docker/syft-lambda/          # multi-stage Dockerfile + .dockerignore
├── eval/                        # labelled set + harness
├── docs/{PRD.md,KIRO_JOURNAL.md,ARCHITECTURE.md,runbooks/}
├── scripts/hooks/
├── .github/workflows/{ci.yml,deploy.yml,vigil.yml}
├── LICENSE (Apache-2.0)  NOTICE  README.md  SECURITY.md
```

## Naming Conventions

- Directories: lowercase, hyphen-separated (`death-certificate`, not `DeathCertificate`).
- Python modules: snake_case. Classes: PascalCase.
- TypeScript/React: kebab-case file names for components, PascalCase for component names.
- Spec directories: kebab-case, matching the spec name from the PRD spec table.
- Terraform modules: one resource family per module; module name = directory name.
- Infrastructure env roots: `envs/dev/` and `envs/prod/` only.
- Hooks: `.kiro/hooks/<name>.json` using kebab-case.
- Agents: `.kiro/agents/<name>.json` using lowercase.
- Runbooks: `docs/runbooks/<topic>.md` using kebab-case.

## Separation Rules

- `backend/core/` contains only pure logic with no I/O. Every function here is property-testable.
- Tests for `backend/core/scoring/` are colocated in `backend/core/scoring/tests/`, with fixtures in `backend/core/scoring/tests/fixtures/`. Tests resolve fixture paths via `Path(__file__).parent`, never the working directory. `backend/tests/` remains for cross-package unit, property, and integration tests.
- `backend/sources/` contains only external API clients and caching. No scoring logic.
- `backend/workflow/` contains Step Functions task handlers only.
- `backend/rites/` contains remediation generators and codemod rules. No scoring.
- `backend/narrate/` contains Bedrock prompts and validators only.
- `infra/modules/` contains reusable Terraform modules. No environment-specific values.
- `infra/envs/` contains thin roots that call modules with tfvars. No resource definitions here.
- `eval/` is standalone; not imported by application code.

## Commit Hygiene

- `.kiro/` must be committed at repo root and never added to `.gitignore`.
- CI must fail if `.kiro` is in `.gitignore`.
- All code written on or after 30 Oct 2026. Pre-existing work disclosed in README "Third-party components".
