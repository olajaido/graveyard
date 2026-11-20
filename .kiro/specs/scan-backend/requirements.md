# Spec: scan-backend (LEAN)

> **Status:** REVISION 2 (19 Nov 2026): review decisions applied (Syft layer instead of container image; permissions granted by task T0; concurrency cap). Design in `design.md`; tasks in `tasks.md`; T0 is done, the rest is not started.
> **Combines PRD specs:** `infra-serverless`, `exhume-github`, `syft-sbom-lambda`, `autopsy-workflow` (PRD §8.1, §8.2, §10.1, §10.4 to §10.6).
> **Goal (Sun 22 Nov, dev):** `POST /v1/scans {source:{type:"github",repo:"olajaido/haunted-house"}}` returns `202 {scanId}`. A Step Functions workflow runs Validate, FetchManifests, GenerateSBOM, BuildGraph, AutopsyMap, Classify, Finalise. `GET /v1/scans/{id}`, `/v1/scans/{id}/graves` and `/v1/scans/{id}/graves/{purl}` return results.
> **Out of scope:** Narrate and Bedrock (no Bedrock call, no guardrail, no `narrative` field). SBOM upload (`type:"sbom"`, `POST /v1/uploads`). `GET /v1/packages/{purl}/autopsy`. Rites, reports, Séance. CloudFront, WAF, the web app (`infra-edge`). Private repos. pnpm lockfiles (the existing graph code does not parse them; see D6).
> **Lean rules (maintainer):** unit and integration tests only; no mutation checks, no bad-sample suites, no verification register; reuse `core`, `sources` and `cli`; the agent never runs `terraform plan/apply` or the `aws` CLI (CI deploys); MANUAL tasks only for the GitHub App key, the App ID and installation ID, and the first dev scan check. A permission the apply roles lack is **listed** (SB-PERM), never worked around.
> **Sources:** steering `product.md`, `security.md`, `tech.md`, `structure.md`, `terraform.md`; specs `infra-foundation` (names, tags, roles, boundary, CI), `mortality-model-v2`, `dependency-graph`, `autopsy-sources`, `graveyard-cli`.

## Glossary for this spec

| Term | Meaning |
|------|---------|
| **Scan** | One run of the workflow for one repo. Identified by `scanId`. |
| **Service** | A directory that holds at least one supported lockfile (EX-6). |
| **Node** | One unique `purl@version` in the merged graph. |
| **Grave** | A node whose state is not Alive (state Resting, Ailing or Dead, or overlay Cursed or Wounded). |
| **Reader app** | The "Graveyard Reader" GitHub App: no repository permissions, public reads only (`security.md`). |
| **Artefacts bucket** | The S3 bucket `graveyard-<env>-artefacts-…` with prefix `scans/<scanId>/`. |
| **Table** | The DynamoDB single table `graveyard-<env>-data` (PRD §10.4). |
| **live** | The Lambda alias that the API and the state machine invoke (`terraform.md`). |

---

## 1. API (SB-API)

| ID | Requirement |
|----|-------------|
| SB-API-1 | WHEN `POST /v1/scans` receives `{source:{type:"github",repo:"<owner>/<name>",ref?:"<ref>"}}` THE `api` function SHALL validate it (SB-VAL-1), write the Scan `META` item with status `QUEUED`, start one execution of the scan state machine with the `live` alias, and return `202 {scanId}`. The body SHALL be at most 4 KB and SHALL contain no unknown field. |
| SB-API-2 | `scanId` SHALL be a ULID followed by `-` and 16 random hex characters (64 bits), made from `secrets`-grade randomness supplied by the handler (PRD §10.4, T4). Every read route SHALL reject an ID that does not match `^[0-9A-HJKMNP-TV-Z]{26}-[0-9a-f]{16}$` with `404`. The execution name SHALL equal `scanId`. |
| SB-API-3 | `GET /v1/scans/{scanId}` SHALL return `{scanId, status, stage, source, createdAt, updatedAt, modelVersion, counts, partial, error}`. `status` is `QUEUED`, `RUNNING`, `COMPLETE` or `FAILED`. `counts` is `{total, alive, resting, ailing, dead, cursed, wounded, unscored}`. `error` is present only when `FAILED` and holds `{code, title}` from a fixed table (SB-ERR-1), never a raw exception text. |
| SB-API-4 | `GET /v1/scans/{scanId}/graves` SHALL return the nodes whose state is not Alive, sorted by `priority` descending then `purl`, with query parameters `state` (`resting`, `ailing`, `dead`; repeatable), `cursed` and `wounded` (boolean), `limit` (1 to 200, default 50) and `cursor` (opaque). An invalid parameter SHALL give `400`. The cursor SHALL carry only an offset and SHALL be validated as a non-negative integer; it never names a key. |
| SB-API-5 | `GET /v1/scans/{scanId}/graves/{purl}` SHALL return the Death Certificate payload of one node: `purl`, `state`, `deadReason`, `cursed`, `wounded`, `mortality`, `confidence`, `priority`, `exposure`, `direct`, `scope`, `services`, `pathCount`, `examplePaths`, `signals`, `evidence` (raw value, normalised risk, source URL, fetch time per signal: AU-3), `contributions`, `warnings`, `asOf`, `modelVersion`. The route SHALL use a greedy path parameter (`{purl+}`), and the handler SHALL percent-decode the purl and validate it with `core.purl` before any table access. It SHALL return `404` for a purl that is not a node of that scan. |
| SB-API-6 | All errors SHALL be RFC 9457 `application/problem+json` with `type`, `title`, `status` and `detail`. `detail` SHALL be a fixed message and SHALL NOT echo user input or exception text. Status codes: 400 invalid input, 404 unknown scan or purl, 413 body too large, 429 throttled, 503 kill switch. |
| SB-API-7 | `backend/api/openapi.yaml` (OpenAPI 3.1) SHALL describe exactly the four routes of this spec, and a test SHALL fail if a route in the router or in the Terraform route list is missing from it, or the reverse (`tech.md`). |
| SB-API-8 | WHEN the SSM parameter `/graveyard/<env>/kill-switch` is `true` THE `api` function SHALL answer `POST /v1/scans` with `503` problem+json and start nothing. `GET` routes SHALL keep working. The value SHALL be cached for at most 60 seconds. |
| SB-API-9 | THE HTTP API stage SHALL set default route throttling (rate and burst from module variables), and `POST /v1/scans` SHALL have a lower limit than the `GET` routes. Access logs SHALL go to the log group `/aws/vendedlogs/states/graveyard-<env>-api-access` (a path the apply role may create) in JSON (request ID, route key, status, latency; no query string, no body, no header). CORS origins SHALL be a module variable, empty by default (no browser origin allowed). WAF and a per-IP limit belong to `infra-edge`. |
| SB-API-10 | A read of a scan SHALL NOT need credentials: scans of public repos are viewable by anyone with the link (PRD §10.4). The route handlers SHALL never accept a table key from the caller; they build keys from the validated `scanId` and purl only. |

## 2. Validate (SB-VAL)

| ID | Requirement |
|----|-------------|
| SB-VAL-1 | THE system SHALL accept only `owner/name` for a repo (`security.md` T2). `owner` SHALL match `^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$`. `name` SHALL match `^[A-Za-z0-9._-]{1,100}$` and SHALL NOT be `.` or `..`. `ref`, when given, SHALL match `^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$` and SHALL NOT contain `..`, `//`, a trailing `/` or a trailing `.lock`. A URL, host name, scheme or whitespace SHALL be rejected. |
| SB-VAL-2 | THE same validation SHALL run in `api` and again in the `validate` task, from the one function in `backend/exhume/validate.py`. The server SHALL build every GitHub URL from the validated parts; no caller-supplied URL is ever fetched. |
| SB-VAL-3 | THE `validate` task SHALL read the limits from SSM (SB-CFG-1), write them into the execution state, set `stage=VALIDATE` and `status=RUNNING`. |

## 3. FetchManifests (SB-FET)

| ID | Requirement |
|----|-------------|
| SB-FET-1 | THE `fetch` task SHALL authenticate with a short-lived installation token of the **Reader app**: sign an RS256 JWT (valid at most 9 minutes, `iat` 60 seconds in the past) with the private key from Secrets Manager `graveyard/<env>/github/reader`, read the App ID and installation ID from SSM, and call `POST /app/installations/{id}/access_tokens`. The token SHALL never be logged, stored or put in the execution state, and SHALL be held in memory only. The key SHALL be read at run time, never from an environment variable. |
| SB-FET-2 | THE task SHALL read the repo tree with the GitHub Trees API (`GET /repos/{owner}/{name}/git/trees/{ref}?recursive=1`, `ref` defaults to `HEAD`), and SHALL fetch file contents by blob SHA from that tree. It SHALL NOT clone and SHALL NOT run code (`product.md`, T9). |
| SB-FET-3 | THE task SHALL keep only files whose base name is `package-lock.json`, `uv.lock`, `poetry.lock` or matches `requirements*.txt` (the names `cli.discover` accepts), and SHALL skip any path that has a segment in `cli.discover.SKIP_DIRS`. It SHALL group them by directory (one service per directory; `.` is the repo root) and SHALL use the same lockfile predicate as the CLI, not a copy. |
| SB-FET-4 | LIMITS (SSM-backed, defaults in SB-CFG-1): at most 50 services (`core.graph.model.DEFAULT_MAX_SERVICES`), at most 10 MB of manifest content in total, at most 5 MB per file. A limit breach SHALL fail the scan with `TOO_LARGE`. A truncated tree (`truncated: true`) SHALL fail with `TREE_TRUNCATED`. |
| SB-FET-5 | THE task SHALL write each file to `s3://<artefacts>/scans/<scanId>/manifests/<service-index>/<file name>` with SSE-KMS and write `scans/<scanId>/services.json` (service path, file names, size, SHA-256, blob SHA). Only the S3 keys and counts SHALL go into the execution state (the 256 KB state limit). |
| SB-FET-6 | A repo that is not found or private SHALL fail with `REPO_NOT_FOUND`; a repo with no supported file SHALL fail with `NO_MANIFESTS`. Both messages SHALL suggest the SBOM upload route (EX-5; the route itself is a later spec). A GitHub rate-limit response SHALL fail with `GITHUB_RATE_LIMITED` after the retries of SB-WF-5. |
| SB-FET-7 | THE task SHALL emit the custom metric `GitHubRateRemaining` from the `x-ratelimit-remaining` header (`tech.md` alarms). |

## 4. GenerateSBOM (SB-SBOM)

| ID | Requirement |
|----|-------------|
| SB-SBOM-1 | THE `syft` function SHALL be a zip Lambda (Python 3.12, arm64) with a **Lambda layer** that holds the Syft v1.56.0 `linux_arm64` binary at `/opt/bin/syft` (ADR 0001, `cli.syft.SYFT_VERSION`). One invocation handles one service and returns only S3 keys. The state machine SHALL run the invocations in parallel with an inline Map (`MaxConcurrency` from a variable). This replaces the container image of PRD §10.2 (deviation D7 in the design). |
| SB-SBOM-2 | THE handler SHALL download the service's manifests from S3 into `/tmp/<random>/`, then call the existing `cli.syft.run_syft` and `cli.syft.check_version` with the executable `/opt/bin/syft` (same environment, same `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES`, same size and timeout limits), and write the CycloneDX document to `scans/<scanId>/sbom/<service-index>.cdx.json`. It SHALL delete `/tmp/<random>/` before it returns. |
| SB-SBOM-3 | THE layer SHALL be built by `scripts/build/build_syft_layer.py`: it downloads `syft_1.56.0_linux_arm64.tar.gz` from the Syft GitHub release at build time, **verifies it against a SHA-256 pinned in `scripts/build/syft-pin.json`** (a mismatch fails the build, nothing is extracted), and writes a deterministic `syft-layer.zip` (`bin/syft`, mode 0755, fixed timestamps). The pin file SHALL hold the version, the URL and the SHA-256 and SHALL be the only place they are written. No `latest`, no unpinned download, and no Syft binary in the repository. |
| SB-SBOM-4 | A Syft failure for one service SHALL fail the scan with `SBOM_FAILED` (as the CLI does: D6 of `graveyard-cli`). The error message from Syft SHALL NOT reach the table or the API. |
| SB-SBOM-5 | THE function SHALL NOT have DynamoDB, Secrets Manager or SSM access. It needs only S3 `scans/*` read and write, KMS use and the layer. |

## 5. BuildGraph (SB-GRAPH)

| ID | Requirement |
|----|-------------|
| SB-GRAPH-1 | THE `graph` task SHALL, for each service, read the SBOM and the lockfiles from S3 into `/tmp`, call `cli.lockfiles.read_scopes` and the existing augmentation (the `_augment` logic of `cli.pipeline`, exported under a public name), and call `core.graph.build_graph` over all services. It SHALL NOT re-implement the graph, scopes or exposure (EX-4, EX-6, EX-7). |
| SB-GRAPH-2 | THE task SHALL write `scans/<scanId>/purls.json` (the unique canonical purls, sorted, a JSON array of strings) and `scans/<scanId>/nodes.json` (per node: purl, `direct`, `scope`, `services`, the `PathInfo` pairs from `exposure_inputs`, `services_affected`, up to the example paths, as JSON). It SHALL write the graph warnings and the CLI warnings into `nodes.json`'s `warnings`. |
| SB-GRAPH-3 | THE task SHALL fail with `TOO_MANY_PACKAGES` when the unique purl count is above the SSM limit (default 2,000), and with `SBOM_INVALID` when `build_graph` raises `ValueError`. Only the fixed error code SHALL be stored. |
| SB-GRAPH-4 | THE task SHALL return to the state machine only `{purlsKey, nodesKey, total, asOf}`, where `asOf` is the UTC date of the run. |

## 6. AutopsyMap (SB-AUT)

| ID | Requirement |
|----|-------------|
| SB-AUT-1 | THE state machine SHALL run a Distributed Map (Express child, `MaxConcurrency` from a variable, default 20) over `purls.json` read with the S3 `ItemReader`, with an `ItemBatcher` of `MaxItemsPerBatch` = 50 (a variable) and `BatchInput` `{scanId, asOf}` (PRD §10.6, AU-1). |
| SB-AUT-2 | EACH batch invocation of the `autopsy` function SHALL: read the package cache item for each purl (SB-DATA-3); for the misses, call the existing `sources.SourceSession.collect` through `cli.pipeline.autopsy_requests`-equivalent code (chunks of `config.limits.max_packages_per_call`, `SourcesConfig.default(contact=<SSM contact>)`, token from the Reader app) and write the successful results back as cache items. It SHALL NOT re-implement fetching, parsing, caching rules or scoring. |
| SB-AUT-3 | A source failure, a timeout or an `ItemError` SHALL NOT fail the batch (AU-4). The handler SHALL return only `{ok, cached, failed:[{purl, code}]}` with fixed codes. Failures are not cached (D3 of `autopsy-sources`). |
| SB-AUT-4 | THE Map SHALL retry the task on Lambda service errors with exponential backoff and jitter (SB-WF-5) and SHALL tolerate up to `ToleratedFailurePercentage` (a variable, default 20) failed batches. A tolerated failed batch SHALL leave its purls without a cache item, which Classify counts as `unscored`. |
| SB-AUT-5 | THE function SHALL emit the metrics `AutopsyCacheHitRate` and `SourceErrors{source}` (`tech.md`) from `SourceStats`. It SHALL have no S3 access and no Bedrock access (`security.md`). |
| SB-AUT-6 | THE function SHALL treat every response text as untrusted: nothing from a response body goes into the table except the parsed scalar fields and fixed templates that `core.sources` already produces (D11 of `autopsy-sources`). |

## 7. Classify (SB-CLS)

| ID | Requirement |
|----|-------------|
| SB-CLS-1 | THE `classify` task SHALL load `nodes.json` and the cached autopsy item of every purl, set `paths` and `services_affected` on each `Signals` from the node (as `cli.pipeline.rank` does), score with `core.scoring.v2.score_package_v2` (model v2: Dead means declared), and order with `core.scoring.sort_results`. It SHALL contain no scoring logic (`tech.md`: LLMs and handlers never compute the score). |
| SB-CLS-2 | THE task SHALL write one `NODE#<purl>` item per node (SB-DATA-2) holding the result, the evidence and the exposure fields, with the 30-day TTL. A node with no autopsy item SHALL be written with `state="unscored"` and no mortality, and SHALL be counted as `unscored`. |
| SB-CLS-3 | THE state value in the API SHALL map as: `base_state` Alive, Resting, Ailing or Dead; `cursed` and `wounded` are separate booleans (glossary). A node is a grave when its base state is not Alive, or it is cursed or wounded. Unscored nodes are not graves but are counted. |
| SB-CLS-4 | THE task SHALL record `modelVersion` (`v2`) on the Scan item. |

## 8. Finalise (SB-FIN)

| ID | Requirement |
|----|-------------|
| SB-FIN-1 | THE `finalise` task SHALL write the counts, `partial` (true when any node is unscored), `status=COMPLETE`, `stage=DONE` and `updatedAt`, and SHALL emit `ScanDurationSeconds`. |
| SB-FIN-2 | WHEN any earlier state fails and is not tolerated THE state machine SHALL go to a `MarkFailed` state that writes `status=FAILED`, `stage` and `errorCode` (from the Catch `Error` name, mapped by SB-ERR-1) to the Scan item through the DynamoDB service integration. No Lambda SHALL be needed to record a failure. |
| SB-FIN-3 | THE overall workflow timeout SHALL be 300 seconds (PRD §10.6). A timeout SHALL end as `FAILED` with code `TIMEOUT` (an `Execution timed out` is not caught by the state machine itself, so the `api` read path SHALL report a `RUNNING` scan older than 10 minutes as `FAILED/TIMEOUT`, SB-ERR-2). |

## 9. Errors (SB-ERR)

| ID | Requirement |
|----|-------------|
| SB-ERR-1 | THE fixed error codes are `INVALID_INPUT`, `REPO_NOT_FOUND`, `NO_MANIFESTS`, `TOO_LARGE`, `TREE_TRUNCATED`, `TOO_MANY_PACKAGES`, `GITHUB_RATE_LIMITED`, `GITHUB_AUTH_FAILED`, `SBOM_FAILED`, `SBOM_INVALID`, `TIMEOUT`, `INTERNAL`. Each has one fixed title in `backend/api/` and one custom exception class that the task handlers raise. An exception class with another name SHALL map to `INTERNAL`. |
| SB-ERR-2 | THE read path SHALL report `FAILED/TIMEOUT` for a scan in `QUEUED` or `RUNNING` whose `createdAt` is more than 10 minutes old (no write is needed). |

## 10. Data model (SB-DATA)

| ID | Requirement |
|----|-------------|
| SB-DATA-1 | THE table SHALL be a DynamoDB single table `graveyard-<env>-data`: on-demand billing, partition key `pk` (S), sort key `sk` (S), TTL attribute `ttl`, point-in-time recovery on, deletion protection and `prevent_destroy` on, SSE with the app CMK, and GSI1 (`gsi1pk`, `gsi1sk`) for "latest scan for repo" (PRD §10.4). GSI1 SHALL be created and written (`gsi1pk = source#<repo>`, `gsi1sk = createdAt`), but no route in this spec reads it. |
| SB-DATA-2 | ITEMS: Scan `SCAN#<scanId>` / `META` (source, status, stage, counts, partial, createdAt, updatedAt, modelVersion, errorCode, ttl 30 d); Scan node `SCAN#<scanId>` / `NODE#<purl>` (SB-CLS-2, ttl 30 d). No item holds file contents, tokens or third-party free text (T6, product principle 6). |
| SB-DATA-3 | Autopsy cache: `PKG#<purl>` / `AUTOPSY#v1` holding the serialised `SourceResult` (signals without exposure, the 11 evidence entries, warnings, repo, versions) and `fetchedAt`, with a 24 h TTL (AU-5). A read SHALL ignore an item whose `ttl` has passed even if DynamoDB has not deleted it yet (TTL deletion can lag). Serialisation SHALL be one pure module with a round-trip test. |
| SB-DATA-4 | THE artefacts bucket SHALL have: SSE-KMS with the app CMK and the S3 Bucket Key, versioning, all four Block Public Access settings, `BucketOwnerEnforced`, a TLS-only policy that also denies non-KMS `PutObject`, and lifecycle rules: `scans/` expires after 7 days (manifests and SBOMs: `security.md` retention), `uploads/` after 7 days, `reports/` after 30 days, noncurrent versions after 1 day, incomplete multipart uploads after 7 days. |
| SB-DATA-5 | THE app CMK SHALL have rotation on, `prevent_destroy`, an alias `alias/graveyard-<env>-app`, the `Project` and `Env` tags (the boundary's `KmsUse` needs them), and a key policy limited to the account root (administration), the apply role's administration actions, and the roles of this spec (`kms:Decrypt`, `kms:GenerateDataKey`, `kms:DescribeKey`) (`security.md`). |

## 11. Workflow (SB-WF)

| ID | Requirement |
|----|-------------|
| SB-WF-1 | THE state machine SHALL be a Standard state machine `graveyard-<env>-scan` with the states `Validate`, `FetchManifests`, `GenerateSBOM` (Map over services), `BuildGraph`, `AutopsyMap`, `Classify`, `Finalise` and `MarkFailed`. It SHALL invoke each Lambda by its `live` alias ARN. The definition SHALL be built with `jsonencode` in `locals` of the `workflow` module. |
| SB-WF-2 | EVERY Task state SHALL have a `Catch` for `States.ALL` to `MarkFailed` that keeps `$.scanId` and the error name. |
| SB-WF-3 | THE data between states SHALL be S3 keys, counts and the `scanId` only. No state output SHALL exceed 256 KB; the Map output of `AutopsyMap` SHALL be discarded (`ResultPath: null`). |
| SB-WF-4 | TRACING (X-Ray) SHALL be on for the state machine. Execution logging SHALL be on at level `ERROR` with `include_execution_data = false` to the log group `/aws/vendedlogs/states/graveyard-<env>-scan` (retention from a variable), so that failures of the Express child executions are visible. The state machine role SHALL carry the log-delivery actions of exception E7. |
| SB-WF-5 | RETRIES: Lambda service errors (`Lambda.ServiceException`, `Lambda.AWSLambdaException`, `Lambda.SdkClientException`, `Lambda.TooManyRequestsException`) SHALL retry up to 3 times with `BackoffRate` 2 and `JitterStrategy: FULL`. A handler error of this spec (SB-ERR-1) SHALL NOT retry, except `GITHUB_RATE_LIMITED` once after a wait. |
| SB-WF-6 | THE state machine SHALL be created with `publish = true` and an alias `live`; `api` SHALL start the alias ARN. |

## 12. Configuration and secrets (SB-CFG)

| ID | Requirement |
|----|-------------|
| SB-CFG-1 | SSM parameters under `/graveyard/<env>/` (Terraform creates them; no value is a literal in a handler): `kill-switch` (`false`), `limits/max-services` (50), `limits/max-manifest-bytes` (10485760), `limits/max-file-bytes` (5242880), `limits/max-purls` (2000), `sources/contact` (the User-Agent contact for `SourcesConfig.default`, a variable), `github/reader/app-id` and `github/reader/installation-id` (value `UNSET`; `ignore_changes = [value]` with a comment; the maintainer sets them, SB-MAN-1). |
| SB-CFG-2 | THE secret `graveyard/<env>/github/reader` SHALL be created as an **empty container** (no `aws_secretsmanager_secret_version`), encrypted with the app CMK, `recovery_window_in_days = 7`. The value is the PEM private key and is set by hand (SB-MAN-1). |
| SB-CFG-3 | HANDLERS SHALL read SSM through Powertools Parameters (cache 60 s) and SHALL read table, bucket, key and secret names from Lambda environment variables set by Terraform (names only; no secret and no token in any environment variable). |
| SB-CFG-4 | THE Bedrock parameters (`bedrock/*`) SHALL NOT be created here. |

## 13. Infrastructure (SB-INF)

| ID | Requirement |
|----|-------------|
| SB-INF-1 | THE modules (Terraform, `structure.md`) SHALL be: `data` (CMK, table, artefacts bucket, kill-switch and limit parameters), `github-app` (reader secret container, App ID and installation ID parameters), `lambda-function` (one function: role, log group, function, version, alias, reserved concurrency), `workflow` (the task functions, the Syft layer, the state machine, its role and log group), `api` (the `api` function, the HTTP API and its access log group) and `observability` (the SNS topic and the alarms of SB-OBS-1). The two env roots call them with the same shape and different variable values (INF-LAY-4). There is no ECR module. |
| SB-INF-2 | EVERY resource name SHALL start with `graveyard-<env>-` (INF-NAME-1), SSM and secret paths SHALL use `/graveyard/<env>/` and `graveyard/<env>/`, the IAM roles SHALL use path `/graveyard-<env>/` and carry `graveyard-<env>-boundary` (INF-APPLY-4), and tags SHALL come from the root `default_tags`; a resource that does not inherit them SHALL get them through `tags` and be listed in the design (INF-TAG-3). |
| SB-INF-3 | EVERY Lambda SHALL be Python 3.12 on `arm64`, with `publish = true`, an alias `live`, X-Ray `Active`, reserved concurrency from a variable (the per-env total is capped at about 50: `autopsy` 20, `api` 8, `fetch` 5, `syft` 5, `validate` 3, `graph` 3, `classify` 3, `finalise` 3; the account limit of 400 is shared), memory and timeout from variables, Powertools env vars (`POWERTOOLS_SERVICE_NAME`, `POWERTOOLS_METRICS_NAMESPACE = Graveyard/<env>`, `LOG_LEVEL`), a log group `/aws/lambda/graveyard-<env>-<name>` with retention from a variable (default 30) and no KMS on the log group. |
| SB-INF-4 | EVERY Lambda SHALL have its own IAM role with the boundary and only the statements in SB-INF-5, built with `jsonencode` in `locals` (`terraform.md`), no `aws_iam_policy_document`, no data source in a module. |
| SB-INF-5 | THE role statements SHALL be (each also needs `logs:CreateLogStream`/`PutLogEvents` on its own log group, `xray:PutTraceSegments`, `xray:PutTelemetryRecords`, and `kms:Decrypt` and `kms:GenerateDataKey` only where the role writes; `kms:Decrypt` only where it reads): `api`: DynamoDB `GetItem`, `Query`, `PutItem` on the table and GSI ARNs; `states:StartExecution` on the state machine alias; SSM read. `validate`: DynamoDB `UpdateItem`; SSM read. `fetch`: reader secret `GetSecretValue`; SSM read; DynamoDB `UpdateItem`; S3 `PutObject` on `scans/*`. `syft`: S3 `GetObject`, `PutObject` on `scans/*` only. `graph`: S3 `GetObject`, `PutObject` on `scans/*`; DynamoDB `UpdateItem`. `autopsy`: reader secret; SSM read; DynamoDB `GetItem`, `PutItem` (and `BatchGetItem`). `classify`: S3 `GetObject` on `scans/*`; DynamoDB `GetItem`, `BatchGetItem`, `PutItem`, `BatchWriteItem`, `UpdateItem`. `finalise`: DynamoDB `UpdateItem`. The state machine role: `lambda:InvokeFunction` on the alias ARNs, `states:StartExecution` on itself and `states:DescribeExecution`, `states:StopExecution` on its executions, S3 `GetObject` and `ListBucket` on the bucket (ItemReader), DynamoDB `UpdateItem` (MarkFailed), X-Ray. No `*` resource except the X-Ray actions (exceptions E1, E2). |
| SB-INF-6 | THE Syft layer SHALL be the layer `graveyard-<env>-syft`, compatible with `python3.12` and `arm64`, built from `syft-layer.zip` (SB-SBOM-3) with `source_code_hash`; only the `syft` function uses it. |
| SB-INF-7 | THE HTTP API SHALL have routes exactly the four of SB-API, `payload_format_version = "2.0"`, a `$default` stage with auto-deploy and the throttling of SB-API-9, and an `AWS_PROXY` integration with the `api` alias. The API execute endpoint SHALL be an output (`api_url`). |
| SB-INF-8 | THE DynamoDB table, the CMK and the artefacts bucket SHALL have `lifecycle { prevent_destroy = true }` (`terraform.md`). |
| SB-INF-9 | Module tests (`terraform test` with `mock_provider`, as in `infra-foundation`) SHALL check, for each module, the names, the tags or `default_tags` pass-through, the role boundary, and the policy JSON against SB-INF-5 and the shared-account rules (INF-SHARED-1 to 4): no write action on a resource that is neither `graveyard-<env>-` nor `/graveyard/<env>/`. |

## 14. Observability (SB-OBS)

| ID | Requirement |
|----|-------------|
| SB-OBS-1 | THE `observability` module SHALL create the SNS topic `graveyard-<env>-alerts` (no subscription; the maintainer subscribes by hand later) and these alarms, all to that topic: per Lambda `Errors` > 5 in 5 minutes and `Throttles` > 0; state machine `ExecutionsFailed` > 2 in 15 minutes; HTTP API 5xx rate > 2 %; DynamoDB `ThrottledRequests` > 0; and the kill switch: a metric filter on the `api` log group that counts the structured log field `killSwitch=true` (the `api` handler logs it once per refused `POST`) with an alarm at >= 1 in 5 minutes. |
| SB-OBS-2 | Powertools Logger SHALL write structured JSON with `correlation_id = scanId`; Tracer SHALL be on; Metrics SHALL use namespace `Graveyard/<env>` with `ScanDurationSeconds`, `AutopsyCacheHitRate`, `SourceErrors{source}`, `GitHubRateRemaining`. No log line SHALL contain a token, a private key, a file's contents or a response body. |

## 15. Security (SB-SEC)

| ID | Requirement |
|----|-------------|
| SB-SEC-1 | THE system SHALL NOT execute user code or install user dependencies (T9): no `npm`, `pip`, test or build step on fetched files. Syft only reads files. Manifest bytes are written to `/tmp` and S3 only. |
| SB-SEC-2 | THE system SHALL NOT fetch any URL taken from a manifest, SBOM, API body or GitHub response, other than the fixed GitHub, deps.dev, OSV, registry and Scorecard hosts that `sources` already uses (T2). |
| SB-SEC-3 | THE reader private key SHALL be read only by `fetch` and `autopsy`, SHALL be held only as long as the JWT is signed, and SHALL NOT be written to `/tmp` (the JWT library reads it from memory). |
| SB-SEC-4 | NO third-party text (README, issue, advisory prose) SHALL be stored or returned in this spec. Package names and versions come from the lockfiles and are returned escaped as JSON only. |
| SB-SEC-5 | EVERY dependency added to `backend/` SHALL be pinned exactly in `pyproject.toml` and `uv.lock`, SHALL be checked with the `check-before-adding-dependency` skill before it is added, and SHALL be recorded in the design's dependency table (T8). |
| SB-SEC-6 | `gitleaks` SHALL stay green (no key, token or account ID in any new file, INF-CFG-1). Test fixtures SHALL use throw-away keys generated at test time. |

## 16. Packaging and CI (SB-CI)

| ID | Requirement |
|----|-------------|
| SB-CI-1 | THE zip Lambdas SHALL share one deployment package `lambda.zip` built by a deterministic script (`scripts/build/build_lambda_zip.py`): dependencies from `uv.lock` for `aarch64-manylinux2014` and Python 3.12 (wheels only), then the code packages (`core`, `sources`, `cli`, `exhume`, `scan`, `api`, `workflow`), sorted entries, fixed timestamps, fixed permissions. The Syft layer zip is built by `build_syft_layer.py` (SB-SBOM-3). Two builds of the same commit SHALL give the same SHA-256 for each zip (tested). |
| SB-CI-2 | THE plan and apply jobs SHALL both build the two zips before Terraform runs and SHALL pass their SHA-256 values as root variables (`lambda_zip_sha256`, `syft_layer_sha256`); the module SHALL fail (a `precondition`) when `filebase64sha256` of a file differs from its variable. Without this, a different zip at apply time could be uploaded unseen under a saved plan. |
| SB-CI-3 | THERE SHALL be no image build, no ECR repository, no image-push job, and no `SYFT_IMAGE_PUSH_ENABLED` variable. |
| SB-CI-4 | CI changes SHALL be limited to: the two zip build steps in the existing composite actions, `uv` setup pinned by SHA, and the guards for the new paths. Actions SHALL be pinned by SHA (INF-VER-4). No `pull_request_target`. |
| SB-CI-5 | `scripts/ci/local-checks.sh all` (fmt, validate, `terraform test`, tflint, checkov, actionlint, guards) SHALL be green for the new modules and both env roots before the work is reported done. |

## 17. Permissions (SB-PERM)

The review of 19 Nov 2026 decided how each gap is closed. **Task T0** makes one bootstrap change in `github-oidc` (amendment A1 of `infra-foundation`) and then stops for the maintainer's local bootstrap apply. Nothing else in this spec edits the bootstrap root.

| ID | Requirement |
|----|-------------|
| SB-PERM-1 | THE apply roles SHALL get `kms:CreateGrant` on `key/*` only with the `Project` and `Env` resource tags and `Bool kms:GrantIsForAWSResource = true` (A1-1). Needed for the DynamoDB table and the secret with the app CMK. |
| SB-PERM-2 | THE apply roles and the boundaries SHALL get approved exception E7: the CloudWatch Logs log-delivery actions on `*` (A1-2), for state machine logs and API access logs. `logs:PutResourcePolicy` is not included. |
| SB-PERM-3 | THE boundaries SHALL get `states:DescribeExecution` and `states:StopExecution` on `express:graveyard-<env>-*` execution ARNs (A1-3), for the Distributed Map. |
| SB-PERM-4 | No ECR permission is needed (no image). A Lambda layer needs only the layer actions that the apply roles already have (`PublishLayerVersion`, `GetLayerVersion`, resource `layer:graveyard-<env>-*`). |
| SB-PERM-5 | IF the first apply or the first scan shows another missing permission (for example `logs:PutResourcePolicy`) THEN it SHALL be listed to the maintainer as a new request, not worked around. |

## 18. Tests (SB-TEST)

| ID | Requirement |
|----|-------------|
| SB-TEST-1 | UNIT tests (pytest, `uv run`) SHALL cover: ID generation and validation; repo and ref validation (accepts and rejects, including the SSRF forms: `http://…`, `a/b/../c`, `owner/name?x`, unicode); tree filtering and grouping; limits; JWT claims (decoded with a test key); installation token request and no-token-in-log; the autopsy and node serialisation round-trip; error mapping; cursor parsing; purl decoding; problem+json shape; the route-to-OpenAPI check (SB-API-7). |
| SB-TEST-2 | HANDLER tests SHALL call each handler with an event, an in-memory table and bucket fake (a small class, not a mocking library) and `httpx.MockTransport` for GitHub and sources, and assert the item writes, the returned state and the error codes. |
| SB-TEST-3 | ONE integration test SHALL run the handlers in order, the way the state machine does (Validate to Finalise), over a fixture repo tree with a recorded Syft SBOM (`spikes/` fixtures), the recorded sources cassette where it covers the purls (otherwise a stub that returns known `Signals`), and the fakes, then call the API handlers and assert the counts and one Death Certificate. The Syft handler test runs the real binary under the existing `syft` marker and is skipped when Syft 1.56.0 is absent. |
| SB-TEST-4 | TERRAFORM tests per SB-INF-9, plus a test that the state machine definition (decoded from the module output) has the seven states in order, a Catch to `MarkFailed` on each Task, `ItemBatcher.MaxItemsPerBatch` equal to the variable, and only `live` alias ARNs. |
| SB-TEST-5 | `uv run ruff check`, `uv run ruff format --check`, `uv run mypy --strict core` and `uv run pytest -q` SHALL stay green; the existing `core`, `sources`, `cli` suites SHALL pass unchanged. New packages SHALL be added to the mypy and ruff config. |

## 19. Manual tasks (SB-MAN)

| ID | Requirement |
|----|-------------|
| SB-MAN-1 | MANUAL (maintainer): after the first dev apply, create the Reader GitHub App (no repository permissions), install it, put the PEM private key into the secret `graveyard/dev/github/reader` and the App ID and installation ID into `/graveyard/dev/github/reader/app-id` and `installation-id`. Same for prod later. Steps in `docs/runbooks/scan-backend.md` without values. |
| SB-MAN-2 | MANUAL (maintainer): after SB-MAN-1, run the first dev scan of `olajaido/haunted-house` with the documented `curl` commands and check the result. |
| SB-MAN-3 | The bootstrap apply after T0 is the maintainer's own step and is a STOP point of the task list, not a MANUAL task of this spec. No other MANUAL task exists. |
