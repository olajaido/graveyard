---
inclusion: fileMatch
fileMatchPattern: "infra/**"
---

# Terraform Steering — Graveyard

## Conventions

- Provider `default_tags` on every resource: `Project=graveyard`, `Env`, `Owner=olajide`, `ManagedBy=terraform`, `CostCentre=kiroween-2026`, `Repo=github.com/olajaido/graveyard`.
- No hard-coded ARNs or account IDs. Use `locals`, `data "aws_caller_identity"`, and variables.
- Config values (model ID, kill switch, limits) live in SSM Parameter Store, not HCL literals.
- One resource family per module in `infra/modules/`.
- Environment roots in `infra/envs/{dev,prod}/` are thin: backend config, tfvars, module calls. No resource definitions here.
- `lifecycle { prevent_destroy = true }` on DynamoDB table, KMS key, and state bucket.
- `lifecycle { ignore_changes = [...] }` only where justified (document inline).

## State

- Separate bootstrap root for state bucket and OIDC role.
- Remote state in S3 with `use_lockfile = true` (native lockfile locking; DynamoDB locking is deprecated).
- State bucket: versioned, encrypted, block public access.
- No local state committed.

## Lambda

- `publish = true` plus a `live` alias.
- API and Step Functions invoke the alias, not `$LATEST`.
- Rollback = repoint the alias.
- Container images pinned by digest, never `latest`.

## S3

- Block public access on all buckets.
- OAC (origin access control) for CloudFront; no public bucket.
- SSE-KMS encryption.
- Versioning on state and artefact buckets.
- TLS-only bucket policy.
- Lifecycle: 7-day expiry for uploads, 30-day for reports.

## CloudFront and WAF

- TLS 1.2+.
- HSTS header.
- Security headers policy: CSP, X-Content-Type-Options, Referrer-Policy, `frame-ancestors none`.
- WAF: AWS managed Common, KnownBadInputs, IP reputation rule sets plus a rate-based rule.

## IAM (least privilege, one role per Lambda)

- `api`: `dynamodb:GetItem/Query/PutItem` on table ARN + index; `states:StartExecution` on scan SM; `s3:PutObject` on `uploads/*`.
- `autopsy`: `dynamodb:GetItem/PutItem` on table; no S3; no Bedrock.
- `narrate`: `bedrock:InvokeModel` on specific inference-profile ARN; `bedrock:ApplyGuardrail` on guardrail ARN.
- `rites`: `secretsmanager:GetSecretValue` on GitHub App secret ARN only; Bedrock as above; S3 read/write `rites/*`.
- No `*` resources except where AWS API requires it (document inline).
- KMS key policy scoped to these roles only.

## Alarms (every one routed to an SNS topic)

- Lambda `Errors` > 5 in 5 min (per function).
- Lambda `Throttles` > 0.
- Step Functions `ExecutionsFailed` > 2 in 15 min.
- API Gateway 5xx rate > 2%.
- DynamoDB `ThrottledRequests` > 0.
- Bedrock `InvocationThrottles` > 0.
- Bedrock daily token usage > 70% of daily cap (custom metric `BedrockTokens`).
- GitHub App rate-limit remaining < 20% (custom metric from `x-ratelimit-remaining` header).
- Per-source error rate > 10% over 15 min (`SourceErrors{source}`).
- Kill switch or degraded mode activated (notify immediately).
- Synthetics canary failure.
- AWS Budgets thresholds (50%, 80%, 100%).
- WAF `BlockedRequests` spike (informational).
