# Runbook: scan backend (dev and prod)

Spec: `.kiro/specs/scan-backend`. No value, key or ID is written in this file. Replace `<env>` with `dev` or `prod`.

## 1. After the first apply: the GitHub App secrets (SB-MAN-1)

CI creates the secret container `graveyard/<env>/github/reader` (empty) and the two parameters
`/graveyard/<env>/github/reader/app-id` and `/graveyard/<env>/github/reader/installation-id` (value `UNSET`).
A scan fails with `GITHUB_AUTH_FAILED` until you set them.

1. Create the app in GitHub: Settings, Developer settings, GitHub Apps, New GitHub App.
   - Name: Graveyard Reader (a different name per env is fine, for example one for dev and one for prod).
   - Webhook: off. Repository, organisation and account permissions: **none**. The app only needs its installation token to read public repositories.
   - Where it can be installed: your account (any account is allowed if you want others' public repos scanned, because the token reads only public data).
2. Note the **App ID** (a number on the app's page).
3. Generate a **private key**. GitHub downloads a `.pem` file.
4. Install the app on your account. The URL of the installation page ends in the **installation ID** (a number).
5. Put the key in the secret. Use the console (Secrets Manager, the secret, Retrieve and Set secret value, plaintext) or, from your own terminal with your own credentials:
   ```
   aws secretsmanager put-secret-value --secret-id graveyard/<env>/github/reader --secret-string file://<path-to-the-pem>
   ```
   Delete the `.pem` file from your machine afterwards.
6. Set the two identifiers:
   ```
   aws ssm put-parameter --name /graveyard/<env>/github/reader/app-id --type String --value <app id> --overwrite
   aws ssm put-parameter --name /graveyard/<env>/github/reader/installation-id --type String --value <installation id> --overwrite
   ```
   Terraform ignores later changes to these values (`ignore_changes`), so a re-apply does not reset them.
7. Rotate the key every 90 days: generate a new key in the app, repeat step 5, then delete the old key in GitHub (`docs/runbooks/rotate-github-app-key.md` when it exists).

The agent does not do these steps and never sees the key.

## 2. First scan (SB-MAN-2)

`api_url` is an output of the env root (`terraform output api_url` locally, or the apply log).
```
curl -sS -X POST "$API_URL/v1/scans" -H 'content-type: application/json' \
  -d '{"source":{"type":"github","repo":"olajaido/haunted-house"}}'
```
Expect `202` and `{"scanId": "...", "status": "QUEUED"}`. Then poll:
```
curl -sS "$API_URL/v1/scans/<scanId>"                      # status, stage, counts
curl -sS "$API_URL/v1/scans/<scanId>/graves?limit=20"       # not-Alive nodes, highest priority first
curl -sS "$API_URL/v1/scans/<scanId>/graves/<percent-encoded purl>"   # one Death Certificate
```
Check: `status` is `COMPLETE`; `counts.total` equals alive + resting + ailing + dead + unscored; every Dead node has `deadReason` `declared` (model v2); the execution is green in the Step Functions console; no `AccessDenied` in the Distributed Map (SB-PERM-5).

## 3. Reading a failed scan

`GET /v1/scans/<scanId>` returns `error: {code, title}`. The code is one of a fixed list:

| Code | Meaning | What to do |
|------|---------|------------|
| `INVALID_INPUT` | the repo or ref is not `owner/name` | fix the request |
| `REPO_NOT_FOUND` | not found or private | use a public repo (SBOM upload comes later) |
| `NO_MANIFESTS` | no supported lockfile (`package-lock.json`, `uv.lock`, `poetry.lock`, `requirements*.txt`; pnpm is not supported yet) | none |
| `TOO_LARGE`, `TREE_TRUNCATED`, `TOO_MANY_PACKAGES` | over a limit in SSM `/graveyard/<env>/limits/*` | raise the limit in the data module only if the cost is acceptable |
| `GITHUB_AUTH_FAILED` | secret or identifiers not set, or the app was removed | section 1 |
| `GITHUB_RATE_LIMITED` | the installation token ran out (5,000 per hour) | wait |
| `SBOM_FAILED`, `SBOM_INVALID` | Syft failed, or its output was not usable | look at the `syft` function log group |
| `TIMEOUT` | no result after 5 minutes (or still running after 10) | look at the execution in the console |
| `INTERNAL` | anything else | see the function log groups `/aws/lambda/graveyard-<env>-*` and the state machine log group `/aws/vendedlogs/states/graveyard-<env>-scan` |

Logs are JSON with `correlation_id` equal to the scan ID. No log line holds a token, a key, a file or a response body.

## 4. Roll back a function or the state machine

Every function and the state machine have a `live` alias; the API and the state machine call the alias.
```
aws lambda list-versions-by-function --function-name graveyard-<env>-<name>
aws lambda update-alias --function-name graveyard-<env>-<name> --name live --function-version <previous version>
```
Terraform moves the alias again on the next apply, so roll forward with a fixed commit soon after. For the state machine use `aws stepfunctions update-state-machine-alias` with the previous version ARN.

## 5. Kill switch

```
aws ssm put-parameter --name /graveyard/<env>/kill-switch --type String --value true --overwrite   # refuse new scans
aws ssm put-parameter --name /graveyard/<env>/kill-switch --type String --value false --overwrite  # allow again
```
`POST /v1/scans` answers `503` within 60 seconds; reads keep working. The alarm `graveyard-<env>-kill-switch-active` fires when a scan was refused. Terraform does not reset the value.

## 6. Alerts

The topic `graveyard-<env>-alerts` has no subscription. Subscribe your address in the SNS console and confirm the email.
## 7. Test the CountBatch state (optional, before merging the ui-core backend PR)
`CountBatch` adds the size of an autopsy batch to `progressExamined` on the scan item (ui-core B2). It is the one place the definition uses `States.MathAdd` inside `States.Format`, which the offline tests can only read as text, so check it once in AWS. Run this with your own credentials; the agent does not.

Pick a finished dev scan ID (the update has `ConditionExpression attribute_exists(pk)`, so the scan must exist). The run adds 6 to its `progressExamined` counter, which the API shows only while a scan is in the `AUTOPSY` stage, so a finished scan is not changed for readers.
1. Save the state (copied from `infra/modules/workflow/main.tf`, state `CountBatch`; the table name is the dev one) as `countbatch.json`:
```
{
  "Type": "Task",
  "Resource": "arn:aws:states:::dynamodb:updateItem",
  "Parameters": {
    "TableName": "graveyard-dev-data",
    "Key": {
      "pk": {
        "S.$": "States.Format('SCAN#{}', $.BatchInput.scanId)"
      },
      "sk": {
        "S": "META"
      }
    },
    "UpdateExpression": "ADD progressExamined :n",
    "ConditionExpression": "attribute_exists(pk)",
    "ExpressionAttributeValues": {
      ":n": {
        "N.$": "States.Format('{}', States.MathAdd(States.MathAdd($.autopsy.ok, $.autopsy.cached), $.autopsy.failedCount))"
      }
    }
  },
  "ResultPath": null,
  "Catch": [
    {
      "ErrorEquals": [
        "States.ALL"
      ],
      "ResultPath": null,
      "Next": "Counted"
    }
  ],
  "Next": "Counted"
}
```
2. Save the input as `input.json`, with a real dev scan ID:
```
{"BatchInput": {"scanId": "<scan id>", "asOf": "2026-11-23"}, "Items": ["pkg:npm/a@1.0.0"], "autopsy": {"ok": 3, "cached": 2, "failedCount": 1}}
```
3. Run it with the state machine's role (`terraform output` of the env root, or the IAM console) and read the result:
```
aws stepfunctions test-state --definition file://countbatch.json --role-arn <state machine role arn> --input file://input.json --inspection-level DEBUG
```
Expect `status` `SUCCEEDED`, `nextState` `Counted`, and in the inspection data an `ExpressionAttributeValues` of `{":n": {"N": "6"}}`. The scan item's `progressExamined` rises by 6.
4. Check the safety net. Remove `autopsy` from the input and run it again. Expect `nextState` `Counted` (the `Catch` continues) and no `FAILED` status. If either step differs, tell the agent: the fallback is to write the counter from the autopsy Lambda with an `UpdateItem` grant (design note N1 of the `ui-core` spec).

