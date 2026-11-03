---
inclusion: always
---

# Security Steering — Graveyard

## Untrusted-Input Handling

- Treat all third-party text (READMEs, issues, changelogs, advisory descriptions) as attacker-controllable input.
- Third-party text never enters rite *generation* prompts; it enters only narrative and Séance prompts.
- Delimit untrusted blocks explicitly in all prompts.
- Apply the Bedrock Guardrails prompt-attack filter on every call that touches third-party text.
- Disable tool use for any model call that processes untrusted text.
- Validate output: no URLs or commands that are not present in the evidence sources.
- Codemods are deterministic rules; the LLM only *chooses* the rule and never writes the rewrite.

## Threat Mitigations (always apply)

- T1 Prompt injection: controls above; red-team fixtures in `backend/narrate` tests.
- T2 SSRF: accept `owner/name` only; the server builds GitHub API URLs; never fetch arbitrary URLs.
- T3 Malicious upload: 5 MB cap at the presigned URL via `content-length-range`; JSON only; streaming parser with depth and size limits; Lambda memory and time limits.
- T4 IDOR: unguessable scan IDs (ULID + 64-bit random); ownership check for authenticated resources; demo rites target the demo repo only.
- T5 PR abuse: the Rites GitHub App has `contents:write` and `pull_requests:write` on selected repos only; draft PRs only; global rate limit; kill switch.
- T6 Secret leakage: Secrets Manager for the GitHub App keys and webhook secret; never in env vars or logs; gitleaks hook and CI; GitHub push protection.
- T7 Cost exhaustion: WAF rate limiting, API throttling, Bedrock token caps, Budgets alarms, kill switch.
- T8 Supply chain of Graveyard: pinned deps with lockfiles; Vigil and the dogfood hook on ourselves; images pinned by digest; Actions pinned by SHA.
- T9 Executing untrusted code: never. No `npm install`, `pip install`, or tests in our infrastructure; resolution is metadata-only.

## IAM Rules

- One role per Lambda function. Every role gets only:
  - CloudWatch Logs for its own log group;
  - `xray:PutTraceSegments` and `xray:PutTelemetryRecords`;
  - `ssm:GetParameter(s)` on `arn:aws:ssm:<region>:<account>:parameter/graveyard/<env>/*`;
  - `kms:Decrypt` on the app CMK, plus `kms:GenerateDataKey` only if the role writes.
- Two GitHub Apps, two secrets:
  - `graveyard/<env>/github/reader`: the "Graveyard Reader" app, with no repository permissions (public reads only). Used by `fetch` and `autopsy`.
  - `graveyard/<env>/github/rites`: the "Graveyard Rites" app, with `contents:write` and `pull_requests:write` on selected repos only. Used by `rites` only.
- `api`: `dynamodb:GetItem/Query/PutItem` on the table and GSI ARNs; `states:StartExecution` on the scan state machine; `s3:PutObject` on `uploads/*` (presign).
- `fetch`: reader secret; `dynamodb:PutItem` on the table.
- `autopsy`: reader secret; `dynamodb:GetItem/PutItem` on the table. No S3, no Bedrock.
- `narrate`:
  - `bedrock:InvokeModel` on the specific EU inference-profile ARN (`arn:aws:bedrock:eu-west-2:<account>:inference-profile/<SSM model id>`);
  - **also** `bedrock:InvokeModel` on the underlying foundation-model ARNs the profile routes to (`arn:aws:bedrock:eu-*::foundation-model/<model id>`), with condition `bedrock:InferenceProfileArn` equal to that profile ARN;
  - `bedrock:ApplyGuardrail` on the guardrail ARN;
  - `dynamodb:UpdateItem` on the table.
- Use `eu.` inference profiles only, never `global.`, so data stays in the EU. Model IDs come from SSM: `/graveyard/<env>/bedrock/narrate-model` (default `eu.anthropic.claude-haiku-5-5`) and `/graveyard/<env>/bedrock/rites-model` (default `eu.anthropic.claude-sonnet-5-5`).
- `rites`: rites secret; Bedrock as for `narrate`; `s3:GetObject/PutObject` on `rites/*`.
- Remaining roles (syft, graph, classify, finalise, state machine) are derived in the `infra-serverless` spec under the same rules.
- No `*` resources except where the AWS API requires it (document inline).
- KMS key policy scoped to these roles only.
- Rotate both GitHub App private keys every 90 days via `docs/runbooks/rotate-github-app-key.md`. Secrets Manager rotation does not apply.

## Secrets

- Never commit secrets to the repo.
- Secrets Manager holds both GitHub App private keys and the webhook secret.
- SSM Parameter Store holds runtime config (model ID, kill switch, limits). These are not secrets.
- MCP config uses environment references, never committed values.
- gitleaks runs on every commit and via the PreToolUse blocking hook.

## Data Retention

- User code is not stored beyond manifests and SBOMs (7-day expiry).
- Only the GitHub username is stored, for PR auth.
- No third-party analytics.
- Autopsy cache: 24 h TTL in DynamoDB.
- Scan data: 30-day TTL.