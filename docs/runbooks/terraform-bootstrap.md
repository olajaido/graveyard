# Runbook: bootstrap the Terraform foundation

Applies `infra/bootstrap` once, from your workstation, and moves its state into the bucket it creates. After this,
CI can plan the `dev` and `prod` roots. Spec: `.kiro/specs/infra-foundation` (requirements INF-BOOT, INF-OIDC, INF-COST).

**Who runs it:** the maintainer, with an AWS administrator session. CI never plans or applies this root, and no CI role
can read its state. **The AWS account is shared with other projects.** Nothing here may import, read through a data
source, or change a resource that this stack did not create: the existing GitHub OIDC provider, the existing anomaly
monitors and any already-active cost allocation tag belong to someone else.

Placeholders in this file: `<account-id>` is your 12-digit AWS account ID, `<bucket>` the state bucket name,
`<key-arn>` the state KMS key ARN. Never paste real values into this file or into a commit.

## 1. Before you start

1. Install Terraform **1.17.2** (`terraform version` prints it). The lock files and saved plans need the same
   version as CI. `infra/.tool-versions` is the one place that records it.
2. Sign in to AWS with an administrator session and confirm the account:
   `aws sts get-caller-identity`. It must be the account you mean to use.
3. Work from a clean checkout of `main`: `git status` shows nothing for `infra/`.

## 2. Shared-account checks (do these first)

| # | Check | How | What to do with the answer |
|---|-------|-----|----------------------------|
| a | The GitHub OIDC provider exists and lists the audience `sts.amazonaws.com` | `aws iam list-open-id-connect-providers`, then `aws iam get-open-id-connect-provider --open-id-connect-provider-arn <provider-arn>` and read `ClientIDList` | Present with the audience: leave `create_oidc_provider = false`. Missing: see section 10. Never import or edit it. |
| b | The account's billing currency | Billing console, Preferences | USD (this account, checked 19 Nov 2026): keep the default (40 USD). GBP: set `budget_limit = { amount = "30", unit = "GBP" }`. |
| c | Which of the cost allocation tag keys `Project` and `Env` are already active | Billing console, Cost allocation tags | Put into `activate_cost_allocation_tag_keys` only the keys that are **not** active. Graveyard never manages an active key (section 8). This account (19 Nov 2026): `Project` is listed but Inactive, so set `["Project"]`; `Env` is not active and is not needed, so leave it out. |
| d | Existing budgets | The Billing console, Budgets, **read only** | The account already has a hand-made, account-wide budget `graveyard-monthly` (USD 30, no filters), found at the first apply on 19 Nov 2026. **Graveyard leaves it alone: never import, edit or delete it.** Graveyard's own budget is `graveyard-project-monthly` (Project tag filter, USD 40 default). A `DuplicateRecordException` means a name clash with another budget: choose a different `budget_name`, never import. |
| e | Existing anomaly monitors | **Do nothing.** Do not list, import or edit them. | The stack creates its own custom monitor `graveyard-project`. |

## 3. Configure

```sh
cd infra/bootstrap
cp terraform.tfvars.example terraform.tfvars   # git-ignored; fill it in
```

Set `allowed_account_ids` (one account), `alert_emails` (1 to 10 addresses), and, if section 2 says so,
`budget_limit`. Leave `create_oidc_provider = false` and set `activate_cost_allocation_tag_keys = ["Project"]`; the first apply activates `Project`.
Check `git status`: `terraform.tfvars` must not be listed.

## 4. First apply, with local state

1. Create `local_backend_override.tf` (git-ignored by `*_override.tf`):
   ```hcl
   terraform {
     backend "local" {}
   }
   ```
2. `terraform init`
3. `terraform plan -out=bootstrap.tfplan`
   - It must create **no** `aws_iam_openid_connect_provider` (with `create_oidc_provider = false`).
   - It must create exactly one anomaly monitor, the custom one, and no other monitor.
   - It must change or destroy **nothing** that Terraform did not create. **If the plan touches an existing resource,
     stop and do not apply.**
   - If you set `create_oidc_provider = true` (section 10): the plan must show no thumbprint error or diff (V4b).
4. **Policy check (V9), part 1: the policies the plan can show.** IAM Access Analyzer reads each policy document.
   A plan leaves out any policy that holds a value known only after the apply (the bucket name and the KMS key ARN),
   so part 1 covers the service policies and the boundaries, and part 2 (step 6) covers the rest.
   ```sh
   terraform show -json bootstrap.tfplan > /tmp/bootstrap-plan.json
   jq -r '.. | objects | select(.type? == "aws_iam_policy") | .values.policy? // empty' /tmp/bootstrap-plan.json |
   while IFS= read -r doc; do
     aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document "$doc" \
       --query 'findings[].[findingType,issueCode,locations[0].span.start.line]' --output text
   done
   rm /tmp/bootstrap-plan.json
   ```
   **Any `ERROR` or `SECURITY_WARNING`: stop before the apply and fix the policy by a reviewed change.**
   Record how many `WARNING` and `SUGGESTION` findings there were (section 14).
5. `terraform apply bootstrap.tfplan`, then delete `bootstrap.tfplan`. Note the outputs.
6. **Policy check (V9), part 2: everything, from the state** (the bucket and key policies and the policies that name
   the bucket). Same loop over `terraform show -json`, and for the other policy types:
   ```sh
   # identity policies (state, plan-state, apply-state, guards): as in step 4 but from `terraform show -json`
   # trust policies:
   aws accessanalyzer validate-policy --policy-type RESOURCE_POLICY \
     --validate-policy-resource-type AWS::IAM::AssumeRolePolicyDocument --policy-document "$doc"
   # the bucket policy:
   aws accessanalyzer validate-policy --policy-type RESOURCE_POLICY \
     --validate-policy-resource-type AWS::S3::Bucket --policy-document "$doc"
   ```
   **A finding of type `ERROR` or `SECURITY_WARNING`: fix by a reviewed change before CI uses these roles.**

## 5. Move the state into the bucket

1. From the outputs, write `infra/bootstrap/backend.hcl` (git-ignored; shape in `backend.hcl.example`):
   `bucket = "<bucket>"` and `kms_key_id = "<key-arn>"` (output `state_kms_key_arn`).
2. Delete `local_backend_override.tf`.
3. `terraform init -migrate-state -backend-config=backend.hcl` and answer **yes**.
4. Check the state is in the bucket and encrypted:
   `aws s3api head-object --bucket <bucket> --key bootstrap/terraform.tfstate` succeeds and shows
   `ServerSideEncryption: aws:kms`.
5. `terraform plan` shows **no changes** (INF-BOOT-5).
6. Delete `terraform.tfstate` and `terraform.tfstate.backup` from `infra/bootstrap/`. `git status` lists neither them
   nor `backend.hcl`.
7. Optional, to try an env root from your machine: write `infra/envs/dev/backend.hcl` and `terraform.tfvars` (shapes in the
   `.example` files), run `terraform init -backend-config=backend.hcl` and `terraform plan`. It shows no changes.

Then set the GitHub variables, the secret and the environments: `docs/runbooks/github-environments.md`.

## 6. Changing the bootstrap root later

From your workstation only, with Terraform 1.17.2:
`terraform init -backend-config=backend.hcl`, `terraform plan`, review, `terraform apply`. A change to a policy needs
the same V9 check as the first apply. CI plans the env roots only.

## 7. Recovery: the bucket exists but the local state is lost

`prevent_destroy` stops an accidental `destroy` of the bucket and the key. If you lost the local state before the
migration, either delete the (empty) bucket, key alias and roles by hand and start again, or import them by name:
`terraform import module.state.aws_s3_bucket.state <bucket>` and the same for the key, alias and roles. Do not import
the OIDC provider or any anomaly monitor: this stack never manages them.

## 8. Cost allocation tags (INF-TAG-4, F2, V7)

The budget and the anomaly monitor are filtered to the `Project` tag. Until `Project` is an **active** cost allocation
tag, and tagged resources have billed, both read 0. Attribution starts on the day a tag is activated and is not
retroactive.

1. Billing console, Cost allocation tags: note which of `Project` and `Env` are already active. **Graveyard does not
   manage an active key at all** (other projects may rely on it).
2. A user-defined key can be activated only after AWS has seen it on a billed resource. In this account AWS has already
   seen `Project` (listed, Inactive, 19 Nov 2026), so the first apply activates it with
   `activate_cost_allocation_tag_keys = ["Project"]`. Afterwards check in the Billing console that `Project` shows
   Active (task T25). A key that AWS has not seen yet would have to wait until a tagged resource has billed.
3. If activation fails because AWS has not seen the key yet, write the error text in section 14 (V7) and retry the
   next day. If it still fails after 48 hours, stop and ask.
4. The tag resource has `prevent_destroy`, so a destroy cannot deactivate a key.

## 9. Missing service-linked roles

The CI roles never create a service-linked role (INF-SHARED-3). If an apply fails with a message that names one,
create it once by hand, with an administrator session:
`aws iam create-service-linked-role --aws-service-name <service>.amazonaws.com`. In an account that other projects
use, most already exist.

## 10. If the shared GitHub OIDC provider is removed or loses its audience (F3)

The CI roles trust the provider by ARN and cannot work without it. This stack does not manage it and cannot repair it.

1. Check section 2a again. If the provider exists but the audience is gone, ask its owner to restore `sts.amazonaws.com`.
2. If the provider is really gone, set `create_oidc_provider = true` in `terraform.tfvars` and apply (section 6). The
   provider is created with `prevent_destroy`. Applying this while the provider still exists fails with an
   "already exists" error, which is safe: change nothing and go back to step 1.

## 11. Accepted risk (O8)

Anyone who can push a branch to this repository can change `ci.yml` in a pull request and use the plan role, which
reads the dev and prod state and can write `plans/*`. Only the maintainer can push, pull requests from forks get no
token, and the version-ID and SHA-256 check in `deploy.yml` stops a plan written from a pull request from being applied.

## 12. What the CI roles cannot do

By design (INF-SHARED): create service-linked roles, write account-wide log policies, set up log delivery, create
CloudFront cache or response-headers policies, change any anomaly monitor, budget or cost allocation tag, or touch a
resource that is not named `graveyard-*` or tagged `Project=graveyard`. If a later spec needs one of these it asks for a
reviewed change to the bootstrap root.

## 13. Hand checks of the roles: deferred

**Deferred to the ship-week security review (PRD section 16, W4).** This spec is complete without them. Until then the
denials are asserted by the module tests and by Access Analyzer (section 4). The review runs H1 to H4 on a throwaway
branch and workflow, H5 to H10 as described, and H11 (decision on API access logging). H7 to H10 need the throwaway branch added to the `dev` environment's
deployment-branch rule: add it, run the checks, remove it at once. Never edit an IAM trust policy by hand (it would
drift from Terraform). If a call that should be denied succeeds, stop, delete what it created, and record the number.

| # | Attempt | Expected | Result |
|---|---------|----------|--------|
| H1 | assume `graveyard-dev-apply` from a job with no environment | access denied on `AssumeRoleWithWebIdentity` | |
| H2 | assume `graveyard-prod-apply` from a job with `environment: dev` | access denied | |
| H3 | a job with `environment: prod` on a branch that is not `main` | blocked by the deployment-branch rule before it runs | |
| H4 | assume the plan role from a branch push (not `main`, not a pull request) | access denied | |
| H5 | with the plan role: `s3api put-object` to `envs/dev/terraform.tfstate` | access denied | |
| H6 | with the plan role: `s3api get-object` on `bootstrap/terraform.tfstate` | access denied | |
| H7 | with `graveyard-dev-apply`: create an SNS topic `graveyard-prod-x` | access denied | |
| H8 | with `graveyard-dev-apply`: read `envs/prod/terraform.tfstate` | access denied | |
| H9 | with `graveyard-dev-apply`: create a role `graveyard-dev/graveyard-dev-x` without the boundary | access denied | |
| H10 | with `graveyard-dev-apply`: `iam:UpdateAssumeRolePolicy` on `graveyard-dev-apply` | access denied | |
| H11 | scan API stage: decide whether access logging may be enabled. Today `access_logs_enabled = false`, so the stage writes no access logs. To check the alternative in a throwaway branch: set the variable to true; CreateStage then fails with "Insufficient permissions to enable logging" unless the apply roles have `logs:PutResourcePolicy`. Record the decision: keep logging off, or approve the action as a new exception | the stage is created with no access logs, or the maintainer approves the exception (scan-backend amendment A2, design section 16) | |
| H12 | WAF logging (infra-edge). Needs log delivery and `logs:PutResourcePolicy`, or an S3 or Firehose destination: a new exception. Today the web ACL has metrics and sampled requests only | decide, and approve or keep off | |
| H13 | The direct `execute-api` URL of the HTTP API bypasses CloudFront and the WAF (prod). Decide whether to close it (custom origin header checked by the API; the secret would live in state) or accept it | decide | |
| H14 | Remove `'unsafe-inline'` from `script-src`: compute per-page hashes after the web build and feed them to the site headers function (for example through a CloudFront KeyValueStore, which needs its own permissions) | decide | |
| H15 | Review exceptions E11 and E12 after the first month; check that prod's `_*.lastrites.dev` pattern is still needed (the prod apply guard denies dev names) | review | |
| H16 | CloudFront standard logs (need an S3 bucket with ACL logging and a log-delivery grant) | decide | |
| H17 | WAF rule review from sampled requests after a week of prod traffic; pin managed rule group versions; consider Count mode for new rules | review | |
| H18 | Move the site upload to a dedicated `graveyard-<env>-site-deploy` role instead of the apply role | decide | |
| H19 | CAA records for `lastrites.dev` (allow only `amazon.com`) and DNSSEC, by hand; the CI roles cannot change those record types | do by hand | |
| H20 | Security headers on error responses: CloudFront does not run viewer-response functions for origin errors, so the 404 page and API 4xx and 5xx get none. For the API, have the API send `nosniff`; for the 404 page, accept or fix | decide | |

## 14. Results to record (no account IDs)

| Item | Result |
|------|--------|
| V4b: first plan with `create_oidc_provider = true` shows no thumbprint problem (only if used) | |
| V7: error text of activating a tag AWS has not seen yet | |
| V9: Access Analyzer, part 1 and part 2: number of ERROR, SECURITY_WARNING, WARNING and SUGGESTION findings | |
| V10: billing currency and the budget limit set | USD, default 40 USD (19 Nov 2026) |
| V15: second plan shows no diff on the anomaly monitor's specification | |
| V16: which of `Project` and `Env` were already active | Neither. `Project` listed, Inactive (activated by the first apply); `Env` not active, not managed (19 Nov 2026) |
| V17: the shared OIDC provider was present with the audience `sts.amazonaws.com` | Present with the audience (19 Nov 2026) |
## 15. Edge permissions (spec infra-edge, task T1 and T2)
Apply this before CI plans the edge modules; without it the plan role cannot read the zone and the apply roles cannot write records. Amendment A5 of `infra-foundation` lists what changes. From your workstation, in `infra/bootstrap`, with Terraform 1.17.2:
1. **Tag the zone.** Console, Route 53, Hosted zones, `lastrites.dev`, Edit hosted zone tags: `Project=graveyard`. No policy relies on it (Route 53 supports no tag conditions); it is for cost allocation.
2. **Zone ID.** In the same console page copy "Hosted zone ID" (starts with `Z`). Add to `infra/bootstrap/terraform.tfvars` (git-ignored): `route53_zone_id = "<the ID>"`. Check `git status` does not list the file.
3. `terraform init -backend-config=backend.hcl`, then `terraform plan -out=bootstrap.tfplan`. **Expected: 6 to add, 6 to change, 0 to destroy.**
   - Add: the policies `graveyard-dev-apply-edge-extra`, `graveyard-prod-apply-edge-extra`, `graveyard-plan-read-edge-extra` and their three attachments.
   - Change (in place, policy text only): `graveyard-dev-apply-edge`, `graveyard-prod-apply-edge`, `graveyard-dev-apply-guard`, `graveyard-prod-apply-guard`, `graveyard-plan-guard`, `graveyard-plan-read-edge`.
   - **No change** to either boundary, to a role, to the state bucket or KMS key, or to the cost resources. If the plan shows anything else, stop and do not apply.
4. **Policy check (V9)** on the new and changed policies only:
   ```sh
   terraform show -json bootstrap.tfplan > /tmp/bootstrap-plan.json
   jq -r '.. | objects | select(.type? == "aws_iam_policy") | select((.values.name? // "") | test("^graveyard-(dev|prod)-apply-(edge|edge-extra|guard)$|^graveyard-plan-(guard|read-edge|read-edge-extra)$")) | .values.policy? // empty' /tmp/bootstrap-plan.json |
   while IFS= read -r doc; do
     aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document "$doc" \
       --query 'findings[].[findingType,issueCode,locations[0].span.start.line]' --output text
   done
   rm /tmp/bootstrap-plan.json
   ```
   Any `ERROR` or `SECURITY_WARNING`: stop and tell the agent the finding. Record the counts of `WARNING` and `SUGGESTION` (section 14). Expect suggestions about the Route 53 condition keys, which Access Analyzer may not know.
5. `terraform apply bootstrap.tfplan`, then delete `bootstrap.tfplan`.
6. `terraform plan` shows **no changes** (INF-BOOT-5).
7. Tell the agent: the plan counts (add, change, destroy), the V9 counts, and any finding. No account ID.
## 16. Region guards: direct calls only (amendment A6, infra-edge task T15)
Apply this before re-running the failed dev deploy. From your workstation, in `infra/bootstrap`, with Terraform 1.17.2:
1. `terraform init -backend-config=backend.hcl`, then `terraform plan -out=bootstrap.tfplan`. **Expected: 0 to add, 3 to change, 0 to destroy.** The three changes are the policies `graveyard-dev-apply-guard`, `graveyard-prod-apply-guard` and `graveyard-plan-guard`, text only. The two boundaries, every role and every other policy show no change. If the plan shows anything else, stop and do not apply.
2. Policy check (V9) on those three policies, as in section 15 step 4 with the filter `^graveyard-(dev|prod)-apply-guard$|^graveyard-plan-guard$`. Any `ERROR` or `SECURITY_WARNING`: stop and tell the agent. Expect no new finding type; the only change is one `Bool` condition per region deny.
3. `terraform apply bootstrap.tfplan`, delete the plan file, `terraform plan` shows no changes.
4. In GitHub Actions re-run the failed jobs of the dev deploy (or push a trivial change). The distributions should now create.
5. Tell the agent the plan counts, the V9 counts and the result of the re-run.
## 17. Managed rule groups in a web ACL (exception E14, amendment A7, infra-edge task T16)
Apply this before re-running the failed prod deploy. From your workstation, in `infra/bootstrap`, with Terraform 1.17.2:
1. `terraform init -backend-config=backend.hcl`, then `terraform plan -out=bootstrap.tfplan`. **Expected: 0 to add, 2 to change, 0 to destroy.** The two changes are the policies `graveyard-dev-apply-edge-extra` and `graveyard-prod-apply-edge-extra`, text only (one new statement, `ExceptionE14`). Nothing else changes: not the guards, not the boundaries, not a role. If the plan shows anything else, stop and do not apply.
2. Policy check (V9) on those two policies, as in section 15 step 4 with the filter `^graveyard-(dev|prod)-apply-edge-extra$`. Any `ERROR` or `SECURITY_WARNING`: stop and tell the agent. A suggestion about the wildcards in the resource is expected: the resource is `global/managedruleset/*/*` by design.
3. `terraform apply bootstrap.tfplan`, delete the plan file, `terraform plan` shows no changes.
4. In GitHub Actions re-run the failed jobs of the prod deploy. The web ACL should now create.
5. Tell the agent the plan counts, the V9 counts and the result of the re-run.
