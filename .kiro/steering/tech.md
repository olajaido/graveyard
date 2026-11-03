---
inclusion: always
---

# Tech Steering — Graveyard

## Non-Negotiables

- LLMs never compute the mortality score; scoring is deterministic code.
- Never execute user code or install user dependencies.
- No hardcoded config: SSM Parameter Store for runtime config, variables/locals in Terraform.
- Pin every dependency, image (by digest) and GitHub Action (by SHA). Never use "latest".
- Least-privilege IAM, scoped to specific resource ARNs.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js static export + TypeScript + Tailwind + Framer Motion |
| Backend | Python 3.12 on Lambda (arm64), AWS Lambda Powertools |
| Orchestration | Step Functions (Standard parent, Express child for Distributed Map) |
| Data | DynamoDB single table, on-demand, TTL |
| Artefacts | S3 with SSE-KMS, lifecycle rules (7-day uploads, 30-day reports) |
| LLM | Amazon Bedrock (Claude via EU cross-region inference profile), Bedrock Guardrails |
| SBOM | Syft (pinned version, pinned image digest) |
| Codemods | ast-grep (JS/TS), LibCST (Python) |
| GitHub auth | GitHub App (not OAuth app or PAT); fine-grained, per-repo, short-lived installation tokens |
| IaC | Terraform ≥ 1.10, S3 backend with native lockfile locking (`use_lockfile = true`) |
| CI/CD | GitHub Actions + OIDC to AWS; no long-lived AWS keys |
| Region | eu-west-2 (London); CloudFront global; ACM cert in us-east-1 |

## Architecture Rules

- No VPC. DynamoDB, S3, Bedrock, Secrets Manager reached over IAM-authenticated endpoints. Revisit if private repos or self-hosted runners are added.
- Single production environment plus local and dev stacks in same AWS account, separated by state key and name prefix.
- Lambdas: `publish = true` plus a `live` alias; API and Step Functions invoke the alias; rollback = repoint alias.
- All API endpoints documented in OpenAPI 3.1 (`backend/api/openapi.yaml` is the source of truth).
- Errors use RFC 9457 `application/problem+json`.
- TypeScript client types generated from the OpenAPI spec.

## Logging and Observability

- Structured JSON logs (Powertools) with correlation ID = scanId.
- X-Ray tracing on every Lambda.
- Custom metrics: `ScanDurationSeconds`, `AutopsyCacheHitRate`, `SourceErrors{source}`, `BedrockTokens`.

## Performance Targets

- p95 scan ≤ 90 s cold for 1,000 unique packages; ≤ 10 s warm.
- Certificate open ≤ 300 ms.
- Landing LCP ≤ 2.5 s on 4G (static, CloudFront-cached).

## Cost Control

- ≤ £30/month while live for judging.
- AWS Budgets alarms at 50%, 80%, 100%.
- Bedrock tokens capped per scan and per day.
- `GRAVEYARD_KILL_SWITCH` SSM parameter switches to cached-demo-only mode.
- Cached-demo mode must look intentional, never broken.

## Error Handling

- A single source failure never fails the scan (AU-4).
- Missing signals lower confidence and continue.
- Graceful degradation: cached-demo mode shows a calm banner, keeps all pages navigable, Haunted House works end to end from cache.

## External Sources and Rate Limits

- deps.dev API v3: no auth; cache aggressively.
- OSV.dev `/v1/querybatch`: no auth; one batch per scan (≤ 1,000 queries).
- GitHub GraphQL: GitHub App installation token (5,000 pts/hr); batch 50 repos per query; skip if deps.dev already has it.
- npm registry: abbreviated metadata for speed; no auth.
- PyPI JSON API: per-package JSON; no auth.
- ecosyste.ms: P1 only; set a contact User-Agent.
