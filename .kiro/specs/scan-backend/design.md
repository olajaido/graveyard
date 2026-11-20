# Design: scan-backend (LEAN)

> Requirements: `requirements.md` in this folder (IDs `SB-*`). Requirements win if the two differ.

## 1. Review points (decide at the single review stop)

| # | Point | Proposal |
|---|-------|----------|
| R1 | **Permissions** (SB-PERM-1 to 3). Decided at review (19 Nov 2026). | Task T0 (done) adds `kms:CreateGrant`, exception E7 and the Express execution statement to `github-oidc` (amendment A1 in `infra-foundation`). The maintainer applies the bootstrap before any other task of this spec. |
| R2 | **Syft as a Lambda layer, not a container** (PRD §10.2 deviation D7). Decided at review. | The `linux_arm64` binary is downloaded at build time and checked against a SHA-256 in `scripts/build/syft-pin.json`. No ECR, no image push, no digest or tag problem. Cost: layer zip size (about 30 MB compressed; the 50 MB direct upload limit holds) and `cli.syft` is called with `/opt/bin/syft`. |
| R3 | **Lambda zip and saved plans.** The apply job runs a saved plan, but the zip is a local file. | Deterministic zip, built in both jobs, hash passed as a variable and checked by a `precondition` (SB-CI-1, SB-CI-2). Risk: if Terraform re-reads the file at apply, a mismatch stops the apply. Confirmed only by the first CI run. |
| R4 | **pnpm-lock.yaml** is in PRD EX-2 P0, but `core.graph` has no pnpm parser and "reuse, do not re-implement" applies. | Not supported in this spec. `NO_MANIFESTS` for a pnpm-only repo. A later spec adds it. |
| R5 | **Autopsy cache shape.** PRD §10.4 caches per `purl`; `autopsy-sources` caches per source fact (`SourceCache`). | Cache per purl (`PKG#<purl>`/`AUTOPSY#v1`, the whole `SourceResult`), as PRD §10.4 says. In-process `MemoryCache` stays for per-source facts inside one batch. No `SourceCache` DynamoDB adapter. |
| R6 | **Account Lambda concurrency.** The account limit is 400 and shared. | Graveyard is capped at about 50 reserved per env: `autopsy` 20 (equal to the Map `MaxConcurrency`), `api` 8, `fetch` 5, `syft` 5, `validate` 3, `graph` 3, `classify` 3, `finalise` 3 = 50. All are variables. |
| R7 | **Abuse of public `POST /v1/scans`.** WAF and per-IP limits are `infra-edge`. | Stage throttling, the kill switch and Standard workflow cost only. Each scan costs a few cents at most; the 5 minute cap and `max-purls` bound it. |

## 2. Architecture

```
POST /v1/scans ─► api (Lambda, live) ─► DDB META(QUEUED) ─► StartExecution(live)
                                                              │
  Standard state machine  graveyard-<env>-scan (X-Ray on)     ▼
  Validate ► FetchManifests ► Map(services){GenerateSBOM} ► BuildGraph ►
  AutopsyMap (Distributed Map, Express child, ItemReader S3 purls.json, batch 50) ►
  Classify ► Finalise            any Catch ► MarkFailed (DynamoDB updateItem)

S3 artefacts  scans/<id>/{manifests/,services.json,sbom/,purls.json,nodes.json}   (7 days)
DDB table     SCAN#<id>/META, SCAN#<id>/NODE#<purl> (30 d)   PKG#<purl>/AUTOPSY#v1 (24 h)
GET /v1/scans/{id} | /graves | /graves/{purl+} ─► api ─► DDB (read only)
```

Reuse map (nothing below is re-implemented):

| Need | Existing code | Change |
|------|---------------|--------|
| Lockfile names, skip dirs | `cli.discover` (`EXACT_LOCKFILES`, `REQUIREMENTS_GLOB`, `SKIP_DIRS`, `_is_lockfile_name`) | rename `_is_lockfile_name` to `is_lockfile_name` (public); keep a private alias |
| Syft run, version check, env | `cli.syft.run_syft`, `check_version`, `locate_syft`, `syft_environment` | none |
| Scopes, direct edges | `cli.lockfiles.read_scopes`, `cli.pipeline._augment` | export `_augment` as `augment_service` (public, same body); CLI imports unchanged |
| Graph, exposure inputs | `core.graph.build_graph`, `exposure_inputs` | none |
| Autopsy | `sources.SourceSession`, `cli.pipeline.autopsy_requests`, `cli.pipeline.make_config` | none (handler passes `CliEnvironment`-like values; see §5.5) |
| Scoring | `core.scoring.v2.score_package_v2`, `core.scoring.sort_results` | none |
| Purl parsing | `core.purl` | none |

New code:

| Package | Kind | Content |
|---------|------|---------|
| `backend/core/scan/` | pure, no I/O | `ids.py` (ULID + suffix from supplied time and bytes; the validation regex), `records.py` (`Signals`/`SourceResult` to and from JSON; node record builder; counts; state mapping; cursor), `errors.py` (codes, titles, exception classes) |
| `backend/exhume/` | GitHub side | `validate.py` (pure: repo, ref), `select.py` (pure: tree entries to services and limits), `github_app.py` (JWT, installation token; the HTTP client is passed in), `trees.py` (tree and blob calls; client passed in) |
| `backend/scan/` | store | `store.py` (Protocols `ScanTable`, `Artefacts` and the boto3 implementations; the clients are passed in), `config.py` (SSM reads through a passed-in getter) |
| `backend/workflow/` | handlers | `validate.py`, `fetch.py`, `syft.py`, `graph.py`, `autopsy.py`, `classify.py`, `finalise.py` (thin: event in, calls, event out), `runtime.py` (Powertools logger, tracer, metrics, boto3 clients, one place) |
| `backend/api/` | handlers | `handler.py` (router), `routes.py`, `problem.py`, `openapi.yaml` |

`structure.md` and PRD §14 are updated by task T14 to list `core/scan/`, `exhume/`, `scan/` and the new Terraform modules (as `infra-foundation` did, INF-LAY-5). `core/scan/` imports only `core.scoring.types`, `core.sources.model`, `core.graph.model`, `core.purl`; it has no `os`, `logging`, `boto3`, `httpx`. `exhume/` and `scan/` read no environment variables: `workflow/runtime.py` is the only place that does.

## 3. State machine

All Task states use `arn:aws:states:::lambda:invoke` with `FunctionName` = `<function arn>:live` and `Payload.$ = $`; `ResultSelector` keeps `Payload`; `ResultPath` writes a named key so `$.scanId` survives. Catch for `States.ALL` goes to `MarkFailed` with `ResultPath: $.error`.

| State | Input (from `$`) | Output added to `$` |
|-------|------------------|---------------------|
| Validate | `{scanId, source}` | `limits` |
| FetchManifests | scanId, source, limits | `fetch: {servicesKey, services: n, files: n, bytes}` |
| GenerateSBOM (Map over `$.fetch.serviceItems`, inline, `MaxConcurrency` var) | `{scanId, index}` per item | `sbom: [{index, sbomKey}]` |
| BuildGraph | scanId, `fetch`, `sbom`, limits | `graph: {purlsKey, nodesKey, total, asOf}` |
| AutopsyMap (Distributed, `ProcessorConfig {Mode: DISTRIBUTED, ExecutionType: EXPRESS}`) | `ItemReader` S3 `GetObject` of `$.graph.purlsKey`, `ItemBatcher {MaxItemsPerBatch: 50, BatchInput {scanId, asOf}}`, `ToleratedFailurePercentage` var, `ResultPath: null` | none |
| Classify | scanId, graph | `classify: {counts}` |
| Finalise | scanId, classify | `{status}` |
| MarkFailed | scanId, error | DynamoDB `updateItem` on `SCAN#<id>/META`: `status=FAILED`, `errorCode = States mapping`, `updatedAt` |

Notes:
- `fetch.serviceItems` is a list of `{scanId, index}` (at most 50 entries, small), so the inline Map needs no S3.
- The error name raised by a handler (`REPO_NOT_FOUND` etc.) arrives as `$.error.Error`. MarkFailed stores it only if it is in the fixed code list: the state uses a `Choice` on `$.error.Error` with one branch per code writing the fixed code, and a default writing `INTERNAL`. This avoids storing any raw text and needs no Lambda. Lambda custom exceptions surface by class name, which `core/scan/errors.py` makes equal to the code.
- A `Retry` block sits before each Catch (SB-WF-5). `GITHUB_RATE_LIMITED` retries once with `IntervalSeconds` 30.
- Timeout 300 s at the top; the API reports a stale scan as `TIMEOUT` (SB-ERR-2).
- `states:StartExecution` for the Distributed Map child runs against the state machine's own ARN. The role statement is in §8.

## 4. Data

### 4.1 Table `graveyard-<env>-data`

| Item | pk | sk | Attributes |
|------|----|----|------------|
| Scan | `SCAN#<scanId>` | `META` | `source{type,repo,ref}`, `status`, `stage`, `counts{…}`, `partial`, `modelVersion`, `errorCode`, `createdAt`, `updatedAt`, `gsi1pk=source#<repo>`, `gsi1sk=createdAt`, `ttl` |
| Node | `SCAN#<scanId>` | `NODE#<purl>` | `state`, `deadReason`, `cursed`, `wounded`, `mortality`, `confidence`, `priority`, `exposure`, `exposureAssumed`, `direct`, `scope`, `services[]`, `pathCount`, `examplePaths[]`, `signals{}`, `evidence{}`, `contributions{}`, `warnings[]`, `asOf`, `ttl` |
| Autopsy | `PKG#<purl>` | `AUTOPSY#v1` | `result` (serialised `SourceResult`), `fetchedAt`, `ttl` |

Item size: a node is a few KB (11 evidence entries with capped strings). `graves` loads all nodes of a scan with one `Query` (at most 2,000 by `max-purls`; a page of 1 MB holds roughly 200 to 300 nodes, so the handler follows `LastEvaluatedKey`), filters, sorts by priority and slices by the offset cursor. This is O(n) per request and is fine for n at most 2,000; a sort key on priority is a later change. `GET .../graves/{purl}` is one `GetItem`.

Table `ttl` is epoch seconds. The reader ignores items whose `ttl` is in the past (SB-DATA-3).

### 4.2 Artefacts

`scans/<scanId>/manifests/<index>/<name>`, `services.json`, `sbom/<index>.cdx.json`, `purls.json`, `nodes.json`. The bucket lifecycle expires the whole `scans/` prefix after 7 days. All writes use SSE-KMS (the bucket default plus a bucket policy that denies non-KMS `PutObject`).

## 5. Components

### 5.1 `core/scan/ids.py`
`new_scan_id(now_ms: int, rand10: bytes, rand8: bytes) -> str`: Crockford base32 of 48-bit time and 80 random bits (26 characters), `-`, 16 hex of 8 bytes. `SCAN_ID_RE`. Pure; the handler passes `time.time_ns()` and `secrets.token_bytes`.

### 5.2 `exhume/validate.py`
`parse_repo(text) -> Repo(owner, name)` and `parse_ref(text) -> str`, raising `InvalidInput`. The regexes are the ones in SB-VAL-1. URL building lives in `trees.py` and takes a `Repo`, never a string.

### 5.3 `exhume/select.py`
`select_services(entries, limits) -> list[ServicePlan]`: `entries` are `{path, type, sha, size}` from the tree. A blob is kept when `is_lockfile_name(basename)` and no path segment is in `SKIP_DIRS` and `size <= max_file_bytes`. Grouped by dirname; sorted by path; limits enforced (`TOO_LARGE`). Pure and property-friendly, but only example tests are required.

### 5.4 `exhume/github_app.py`
`make_jwt(app_id, pem, now) -> str` (RS256, `iss`, `iat = now-60`, `exp = now+540`). `installation_token(client, app_id, installation_id, pem, now) -> SecretToken` using the existing `core.sources.secret.SecretToken` so logging redaction already applies. `client` is an `httpx.Client` passed in with `base_url="https://api.github.com"`, timeouts and the headers `Accept: application/vnd.github+json`, `X-GitHub-Api-Version` and a User-Agent with the contact from SSM. Library: PyJWT with the `cryptography` backend (R-dep below).

### 5.5 `workflow/autopsy.py`
```
event: {scanId, asOf, Items: [purl, …]}                 # Distributed Map batch
1. cache.get_many(items) -> hits, misses                # PKG#/AUTOPSY#v1, ttl check
2. token = installation_token(...)                      # once per container, in memory
3. results, stats = asyncio.run(autopsy_requests(misses_with_asOf, env, None, SystemClock(), config=make_config(env)))
4. for ok results: cache.put(purl, serialise(result))   # failures are not cached
5. return {ok, cached, failed:[{purl, code}]}
```
`env` is a small `CliEnvironment`-compatible value built from SSM and the secret (`token`, `contact`); if `CliEnvironment` needs fields that make no sense here, `autopsy_requests` is called through a tiny local protocol, not a copy of its body (decided at T6 from the real signature). Metrics from `SourceStats`.

### 5.6 `workflow/classify.py`
`BatchGetItem` the autopsy items (100 keys per call; the code chunks by 100 and retries `UnprocessedKeys`), rebuild `Signals` with `dataclasses.replace(signals, paths=…, services_affected=…)`, `score_package_v2`, `sort_results`, then `BatchWriteItem` the nodes (25 per call, retries unprocessed). Counts computed in `core/scan/records.py`.

### 5.7 `syft` function (zip + layer)
`handler(event)`: `event={scanId, index}`; reads `services.json` for the service; downloads its files; `ServiceDir(path, Path(tmp), names)`; `exe = "/opt/bin/syft"` (the layer); `check_version(exe, env)`; `bom = run_syft(exe, service, all_paths, timeout, syft_environment({}))`; puts the SBOM. `CliError` becomes `SBOM_FAILED`. The zip carries the whole backend so `cli.syft` is importable. `/opt/bin/syft` is executable because the layer zip stores mode 0755.

### 5.8 API
`handler.py` routes on `routeKey`: `POST /v1/scans`, `GET /v1/scans/{scanId}`, `GET /v1/scans/{scanId}/graves`, `GET /v1/scans/{scanId}/graves/{purl+}`. For the purl route the handler takes the **raw path** (`rawPath`), strips the fixed prefix, applies `urllib.parse.unquote` once and validates with `core.purl`. `openapi.yaml` is hand-written and checked by a test against the router table, which is also the source of the Terraform route list (the module takes the list of route keys as a variable; a test compares it to the router).

## 6. Terraform

| Module | Resources | Inputs of note | Outputs |
|--------|-----------|----------------|---------|
| `data` | `aws_kms_key` + alias, `aws_dynamodb_table` (+GSI1, TTL, PITR, SSE CMK), `aws_s3_bucket` + versioning, SSE-KMS, public access block, ownership, policy, lifecycle; SSM `kill-switch`, `limits/*`, `sources/contact` | `name_prefix`, `env`, `account_id`, `partition`, `region`, `role_arns` (for the key policy), `limits`, `contact` | key and table and bucket ARNs and names, parameter ARN pattern |
| `github-app` | `aws_secretsmanager_secret` (no version), two `aws_ssm_parameter` (`UNSET`, `ignore_changes`) | `name_prefix`, `env`, `kms_key_arn` | secret ARN, parameter names |
| `lambda-function` | role (path `/graveyard-<env>/`, boundary), inline policy from `statements` input, log group, `aws_lambda_function` (zip, optional layers), version, `live` alias, reserved concurrency | `name`, `package_type`, `filename` or `image_uri`, `handler`, `memory`, `timeout`, `reserved_concurrency`, `environment`, `statements`, `boundary_arn`, `zip_sha256` | alias ARN, function name, role ARN |
| `workflow` | seven task functions through `lambda-function` (`syft` with the layer `graveyard-<env>-syft`), the state machine (`publish = true`, alias `live`, logging at `ERROR` to `/aws/vendedlogs/states/graveyard-<env>-scan`), its role | variables for batch size, concurrency, tolerated failure %, timeouts, `lambda_zip`, `syft_layer_zip` and their hashes, `data`/`github-app` outputs | state machine alias ARN, name |
| `api` | `api` function through `lambda-function`, `aws_apigatewayv2_api`, integration, routes, `$default` stage with throttling and JSON access logs to `/graveyard/<env>/api-access`, Lambda permission | `routes` (list), `cors_origins`, throttles, `state_machine_alias_arn` | `api_url`, API id |
| `observability` | SNS topic, alarms | names of functions, state machine, API, table | topic ARN |

Notes:
- Modules contain no `data` source. Roots pass `account_id`, `partition`, `region` from `data.aws_caller_identity`, `data.aws_partition`, `data.aws_region` (allowed by INF-LAY-2). All ARNs are built from those in `locals`.
- Cycles are avoided: `api` takes the state machine alias ARN; `workflow` does not depend on `api`; the CMK key policy lists role ARNs built by name from the prefix (known before creation), not from the role resources.
- Tags: provider `default_tags` cover Lambda, DynamoDB, S3, KMS, SNS, API Gateway, SFN, log groups, secrets and SSM. A `tags` argument is passed explicitly where `default_tags` is not applied to a resource type (checked per module by the INF-TAG-3 test: the design lists none today; add here if the provider docs show one).
- Variable values that differ by env (memory, reserved concurrency, retention, throttle) are variables with defaults in the module and a value in each env root's `locals.tf`/`variables.tf`. Both roots have the same module calls (INF-LAY-4).
- Prod: the existing `deploy.yml` waits for the `prod` environment's reviewer. No change.

## 7. CI and packaging

- `scripts/build/build_lambda_zip.py` (stdlib + `uv` subprocess): `uv export --frozen --no-dev --extra aws --no-emit-project`, `uv pip install --target build/ --python-platform aarch64-manylinux2014 --python-version 3.12 --only-binary :all: --no-deps -r …`, copy code packages, write a zip with sorted names, `ZipInfo.date_time = (2026,1,1,0,0,0)`, `external_attr = 0o644<<16`, deflate level fixed; prints the SHA-256. Test: two builds of a small temp tree give equal hashes.
- `scripts/build/build_syft_layer.py` downloads the pinned Syft release tarball (URL, version and SHA-256 in `scripts/build/syft-pin.json`), refuses to extract on a hash mismatch, and writes `syft-layer.zip` with `bin/syft` mode 0755 and fixed timestamps; prints the SHA-256 of the zip.
- Plan and apply composite actions get a step `Build the Lambda packages` (setup-uv pinned by SHA, then both scripts) and pass `TF_VAR_lambda_zip_sha256` and `TF_VAR_syft_layer_sha256`.
- `scripts/ci/guards.py` gets: the Syft pin file must hold a version, an https URL and a 64-hex SHA-256, and no file under `scripts/build/` may name `latest`; `.kiro` check unchanged.

## 8. IAM statements (SB-INF-5), as `jsonencode` locals

Common to all Lambda roles: logs on `log-group:/aws/lambda/graveyard-<env>-<fn>:*`; `xray:PutTraceSegments` and `xray:PutTelemetryRecords` on `*` (E1, E2); `kms:Decrypt`/`GenerateDataKey` on the CMK ARN (by key id, passed in) as per role.

State machine role: `lambda:InvokeFunction` on each alias ARN; `states:StartExecution` on `stateMachine:graveyard-<env>-scan` (and its alias); `states:DescribeExecution`, `states:StopExecution` on `execution:graveyard-<env>-scan:*`; `s3:GetObject` on `bucket/scans/*` and `s3:ListBucket` on the bucket with a `s3:prefix` condition `scans/*`; `dynamodb:UpdateItem` on the table; `kms:Decrypt`, `kms:GenerateDataKey` on the CMK; X-Ray E1, E2.

All of these fit the boundary's `LogsWrite`, `SsmRead`, `KmsUse`, `DynamoDbItems`, `S3Objects`, `StatesExecute`, `LambdaInvoke`, `SecretValues`, `ExceptionE1/E2`, `ExceptionE7` (log delivery), `StatesExpressExecutions`. `DynamoDbItems` includes `BatchWriteItem`, `BatchGetItem`. `S3Objects` has no `DeleteObject`, so no function deletes (the lifecycle does). Two items the boundary does not give: Express execution ARNs (SB-PERM-5) and nothing else.

## 9. Permission check against the existing policies (SB-PERM)

Read from `infra/modules/github-oidc/policies_actions.tf`, `policies_apply_services.tf`, `policies_apply_core.tf`, `boundary.tf` on the current branch.

| Resource | Needed by Terraform | Present | Result |
|----------|--------------------|---------|--------|
| Lambda | Create, UpdateCode, UpdateConfiguration, PublishVersion, Create/UpdateAlias, PutFunctionConcurrency, AddPermission, Tag | yes (`lambda_write`) | OK. Reads (`GetFunction`, `GetPolicy`, `ListVersionsByFunction`, `ListAliases`) yes |
| Lambda layer | `PublishLayerVersion`, `GetLayerVersion` (the function create reads the layer), `DeleteLayerVersion` on `layer:graveyard-<env>-*` | yes (`layer_write`, `layer_read`) | OK |
| ECR | none (no image) | n/a | OK; no ECR in this spec |
| Step Functions | Create/Update/Delete, `PublishStateMachineVersion`, `CreateStateMachineAlias`, Tag | yes (`sfn_write`) | OK |
| SFN logging | `logs:CreateLogDelivery`, `GetLogDelivery`, `UpdateLogDelivery`, `DeleteLogDelivery`, `ListLogDeliveries`, `DescribeResourcePolicies`, `DescribeLogGroups` | **added by T0** (exception E7, apply `ops` policy and boundary). `logs:PutResourcePolicy` is not included | OK; see SB-PERM-5 if the first apply asks for it |
| API Gateway HTTP API | `apigateway:POST/PUT/GET/PATCH/DELETE` on `/apis/*` with tags | yes (`CreateHttpApis`, `ManageHttpApis`) | OK; access logs use E7 |
| DynamoDB table | Create, UpdateTable, UpdateTimeToLive, UpdateContinuousBackups, Tag | yes | OK |
| DynamoDB with CMK | caller `kms:CreateGrant` on the key | **added by T0** (`KmsCreateGrant`, tags and `GrantIsForAWSResource`) | OK |
| KMS key | CreateKey (tag), PutKeyPolicy, EnableKeyRotation, alias | yes | OK |
| S3 | bucket, policy, versioning, encryption, lifecycle, public access, ownership, tags | yes (`s3_write`) | OK |
| SSM | PutParameter, Tag | yes | OK |
| Secrets Manager | CreateSecret (container), Tag, Describe | yes | OK (no `PutSecretValue`, by design) |
| Secret with the CMK | caller `kms:GenerateDataKey`/`Decrypt` on the key to create the container | not needed for an empty secret (assumed; first apply will show) | watch at first apply |
| SNS, CloudWatch alarms, Logs (Lambda log groups) | Create, SetAttributes, PutMetricAlarm, CreateLogGroup, retention | yes | OK |
| IAM roles | CreateRole under `/graveyard-<env>/` with the boundary, PutRolePolicy, PassRole to `lambda`, `states`, `apigateway` | yes | OK |
| X-Ray | none from Terraform | n/a | OK |
| Plan role reads | same services | assumed symmetric to the above; a missing read shows in the first PR plan | watch |

## 10. Dependencies

New Python dependencies (extra `aws` in `pyproject.toml`, exact pins, checked with the `check-before-adding-dependency` skill in T1 before they are added; versions are decided there, not here): `aws-lambda-powertools` (Logger, Tracer, Metrics, Parameters) with its X-Ray extra, `boto3` (pinned to the version in the Lambda Python 3.12 runtime for parity, also used for the container image), `PyJWT` with `cryptography` (RS256). Test: no new test dependency (fakes are plain classes). `mypy --strict core` stays limited to `core`; the new packages get `mypy --strict` on `core/scan`, and a looser check on handlers is acceptable only if boto3 stubs are not added (decided at T0).

## 11. Test plan

| Layer | What | Where |
|-------|------|-------|
| Unit | IDs, validation, selection, JWT, serialisation, cursor, problem+json, route/OpenAPI | `core/scan/tests/`, `exhume/tests/`, `scan/tests/`, `api/tests/` |
| Handler | each handler with fakes and `MockTransport` | `workflow/tests/` |
| Integration | handlers in state-machine order, then the API | `tests/integration/test_scan_flow.py` |
| Syft | real binary, `syft` marker | `workflow/tests/test_syft_real.py` |
| Terraform | `terraform test` per module, ASL decode test in `workflow` | `infra/modules/*/tests/` |
| Static | `local-checks.sh all`, ruff, mypy, pytest | existing |

The state machine itself is not executed by the agent. Its first real run is the manual dev scan (SB-MAN-2).

## 11a. Deviation D7 (PRD §10.2)
PRD §10.2 and `tech.md` name "Syft (pinned version, pinned image digest)" in a container Lambda. This spec uses a Lambda layer with the Syft binary instead: build-time download, SHA-256 pin, no ECR. Reasons: no image push permission or pipeline, no digest and plan ordering problem, same handler code. The PRD and `tech.md` are updated by task T14.

## 12. Risks

| Risk | Handling |
|------|----------|
| First apply asks for `logs:PutResourcePolicy` or another permission | Stop and list it as a new request (SB-PERM-5). No workaround. |
| Zip hash mismatch between plan and apply | Precondition stops the apply (safe). Fix is in the build script. |
| Distributed Map needs a permission the boundary lacks | Express execution ARNs are covered by T0 (A1-3). Anything else shows at the first scan and is listed (SB-PERM-5). |
| GitHub tree `truncated` for very large monorepos | Fails with `TREE_TRUNCATED`; a per-directory fetch is a later change. |
| Deps.dev or OSV slow for 2,000 purls in 5 minutes | `max-purls` and the 20 percent batch tolerance; cached batches speed up reruns. A real timing is a dev-scan check. |
| Syft layer: binary build mismatch or cold start | The hash pin stops a wrong binary; memory 1 GB, timeout 120 s; the Map runs services in parallel. |
