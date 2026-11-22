# Spec: infra-foundation

> **Status:** requirements reviewed (18 Nov 2026, rounds 1 to 3). The maintainer's decisions on C1–C8, O1–O9, SA1–SA5 and the round-3 flags F1–F7 (exceptions E1–E6 approved) are applied below and recorded in "Decisions taken in review". Design in `design.md`, tasks in `tasks.md`.
>
> **Source of truth:** `docs/PRD.md` §10.2 (rows IaC, CI/CD, Region), §10.3 (no VPC; one account with `dev` and prod separated by state key and name prefix), §12 (Cost row and §12.1 Budgets alarm), §13 (T6, T7, T8; §13.2 "no `*` resources"), §14 (`infra/` layout) and §14.1 (Terraform conventions), §16 W0 ("Terraform bootstrap (state, OIDC)"), §2.4 (public repo; `.kiro` not ignored), §17 (tflint, terraform fmt, checkov, actionlint) and §17.1 (pipeline, plan and apply roles, Terraform plugin cache); steering `tech.md`, `security.md`, `structure.md`, and `terraform.md` and `testing.md` (CI/CD section), which say the same things for `infra/**`.
>
> **Scope:** the base every other infra spec builds on:
> - the `infra/` layout: `infra/bootstrap`, `infra/modules/{state,github-oidc,cost}`, `infra/envs/dev` and `infra/envs/prod`;
> - the Terraform state bucket, created by the bootstrap root with local state and then migrated into itself;
> - version pinning, provider `default_tags`, naming, and the rule that no account ID or hard-coded value is committed;
> - the GitHub Actions OIDC provider (reused from the shared account by default; created only when `create_oidc_provider` is true), one plan role (read-only) and two apply roles (`graveyard-dev-apply`, `graveyard-prod-apply`), and a permissions boundary per env;
> - the Terraform jobs of `.github/workflows/ci.yml` (static checks, `terraform test`, plan) and `.github/workflows/deploy.yml` (apply, environment-gated);
> - the `ci.yml` check that `.kiro/` is not git-ignored;
> - an AWS Budgets budget and a custom Cost Anomaly Detection monitor, both filtered to the `Project` cost allocation tag, with email subscribers;
> - the region rule (eu-west-2), with the us-east-1 ACM certificate recorded for `infra-edge`.
> - the shared-account rules: every write action of the CI roles and boundaries is limited to Graveyard names, paths or the `Project` tag (INF-SHARED).
>
> **Shared account (decision of 18 Nov 2026).** The AWS account is shared with other projects. This spec never imports, adopts or changes an account-level resource it did not create: the existing GitHub OIDC provider and the existing anomaly monitors are left alone, and cost controls look at Graveyard-tagged spend only.
>
> **Out of scope:** see "Belongs elsewhere". This spec creates no application resource (no Lambda, table, bucket other than the state bucket, CloudFront, WAF, SNS topic or alarm).

---

## Glossary for this spec

| Term | Meaning |
|------|---------|
| **Root** | A Terraform root module with its own state: `infra/bootstrap`, `infra/envs/dev` or `infra/envs/prod`. |
| **Env** | `dev` or `prod`. Both live in the same AWS account (PRD §10.3). |
| **Env prefix** | `graveyard-<env>`. Every named AWS resource of an env root starts with `graveyard-<env>-`. |
| **Account-level resources** | The resources of the bootstrap root (INF-BOOT-1). They serve both envs and are applied only by the maintainer. |
| **State bucket** | The S3 bucket that holds the state of all three roots and the saved plans. |
| **State key** | The object key of one root's state in the state bucket. |
| **Plan role** | `graveyard-plan`, assumed by `ci.yml` through OIDC. Read-only on AWS, with writes only to `plans/*` and the env `.tflock` keys. |
| **Apply role** | `graveyard-dev-apply` or `graveyard-prod-apply`, assumed by `deploy.yml` through OIDC, each limited to its own env. |
| **Workload role** | Any IAM role that a later spec creates through an apply role (for example one role per Lambda). |
| **Workload boundary** | The IAM permissions boundary for an env (`graveyard-dev-boundary`, `graveyard-prod-boundary`) that every workload role of that env must carry. |
| **Maintainer** | The human (Olajide) who applies the bootstrap root locally with personal AWS credentials. |

---

## Layout and versions

| ID | Requirement |
|----|-------------|
| INF-LAY-1 | THE system SHALL have three roots, `infra/bootstrap`, `infra/envs/dev` and `infra/envs/prod`, and reusable modules under `infra/modules/<name>/`, one resource family per module (`structure.md`). This spec adds the modules `state`, `github-oidc` and `cost`. Module directories are hyphenated (`structure.md`); module labels in code (`module "github_oidc"`) may stay snake_case. |
| INF-LAY-2 | THE env roots SHALL contain only the backend block, provider configuration, variables, locals, outputs and module calls. They SHALL NOT declare `resource` blocks (`structure.md`, `terraform.md`). `data` sources for the caller identity, partition and region are allowed. |
| INF-LAY-3 | THE modules SHALL contain no environment-specific value. Every value that differs between dev and prod SHALL be a module input. |
| INF-LAY-4 | THE dev and prod roots SHALL have the same module calls and differ only in variable values, so that a change planned on dev is the change applied to prod. |
| INF-LAY-5 | THE `structure.md` steering file and PRD §14 SHALL be updated to list the modules `state`, `github-oidc` and `cost`, the bootstrap root's account-level contents, and any new CI helper paths the design adds. The edit is recorded in this spec and made by a task, not silently. |
| INF-VER-1 | Every root SHALL declare `required_version = ">= 1.10, < 2.0"`, and CI SHALL install one exact Terraform version (the same for all jobs), recorded in a single place in the repo. |
| INF-VER-2 | Every root and module SHALL declare each provider in `required_providers` with an exact version (`= x.y.z`). Each root and module directory SHALL commit its `.terraform.lock.hcl` with hashes for at least `linux_amd64` (CI), `darwin_arm64` (the maintainer's machine) and `linux_arm64` (the pinned container images on an arm64 host). |
| INF-VER-3 | WHEN CI runs `terraform init`, THE workflow SHALL use `-lockfile=readonly` so that a provider not in the committed lock file fails the job. |
| INF-VER-4 | tflint, the tflint AWS ruleset, checkov and actionlint SHALL be pinned to exact versions. Every third-party GitHub Action SHALL be pinned by full commit SHA with the version in a trailing comment (`tech.md`, T8). No tool or image SHALL use `latest`. |

## State

| ID | Requirement |
|----|-------------|
| INF-STATE-1 | THE bootstrap root SHALL create one state bucket in eu-west-2, named `graveyard-tfstate-<random suffix>`, with: versioning enabled; default encryption SSE-KMS with a customer-managed KMS key dedicated to state (the state key), with key rotation enabled and the S3 Bucket Key enabled; all four S3 Block Public Access settings on; object ownership `BucketOwnerEnforced`. |
| INF-STATE-2 | THE state bucket policy SHALL deny every request where `aws:SecureTransport` is `false`, and SHALL deny `s3:PutObject` that asks for any server-side encryption other than SSE-KMS. |
| INF-STATE-3 | THE state bucket SHALL have a lifecycle configuration that: expires noncurrent versions under `bootstrap/` and `envs/` after a configurable number of days while keeping a configurable number of the newest noncurrent versions; expires current objects under `plans/` after 7 days and their noncurrent versions after 1 day; removes expired object delete markers; and aborts incomplete multipart uploads after 7 days. |
| INF-STATE-4 | THE state bucket and the state KMS key SHALL have `lifecycle { prevent_destroy = true }` (PRD §14.1). |
| INF-STATE-5 | Every root SHALL use the `s3` backend with `use_lockfile = true`, `encrypt = true` and `kms_key_id` set to the state key. No root SHALL use a DynamoDB lock table. |
| INF-STATE-6 | Each root SHALL have its own state key: `bootstrap/terraform.tfstate`, `envs/dev/terraform.tfstate` and `envs/prod/terraform.tfstate`. |
| INF-STATE-7 | THE backend block SHALL NOT contain the bucket name or the KMS key ARN. They SHALL be supplied by partial backend configuration: locally a gitignored `backend.hcl` (with a committed `backend.hcl.example` per root); in CI, the bucket name from the GitHub Actions **repository variable** `TF_STATE_BUCKET` (not a secret) and the key ARN built at run time without committing the account ID (INF-CFG-1). |
| INF-STATE-8 | No state file, plan file, `backend.hcl` or `*_override.tf` SHALL be committed. THE repo SHALL keep the existing `.gitignore` entries for `*.tfstate` and `*.tfstate.*` and add `*.tfplan`, `backend.hcl` and `*_override.tf`. |
| INF-STATE-9 | THE state KMS key policy SHALL keep the standard account-root statement (so the maintainer's IAM admin can manage and use the key and the key cannot be locked out), and SHALL grant the plan role and the two apply roles only `kms:Encrypt`, `kms:Decrypt`, `kms:GenerateDataKey` and `kms:DescribeKey`, and only through S3 in eu-west-2 (`kms:ViaService`). The CI roles' identity policies SHALL carry the same limits. |

## Bootstrap (account-level resources)

| ID | Requirement |
|----|-------------|
| INF-BOOT-1 | THE bootstrap root SHALL hold every account-level resource that Graveyard owns: the state bucket, the state KMS key, the GitHub OIDC provider (only when `create_oidc_provider` is true, INF-OIDC-1), the plan role, the two apply roles, the two workload boundaries, the AWS Budget, and the custom Cost Anomaly Detection monitor and subscription. |
| INF-BOOT-2 | THE bootstrap root SHALL first be applied by the maintainer with local state. WHEN the state bucket exists, THE maintainer SHALL configure the S3 backend and run `terraform init -migrate-state` to move the bootstrap state to `bootstrap/terraform.tfstate`, then delete the local state file and its backup. |
| INF-BOOT-3 | THE bootstrap root SHALL only be applied by the maintainer from a workstation. CI SHALL run `fmt`, `validate`, tflint, checkov and `terraform test` on it, and SHALL NOT plan or apply it. No CI role SHALL be able to read the bootstrap state. |
| INF-BOOT-4 | THE bootstrap procedure (first apply, migration, re-apply after a change, the shared-account checks of INF-OIDC-10 and INF-TAG-4, and recovery when the state bucket already exists) SHALL be written in `docs/runbooks/terraform-bootstrap.md`. It SHALL contain no `terraform import` command for the existing OIDC provider or any existing anomaly monitor. |
| INF-BOOT-5 | IF the bootstrap root is applied a second time with no code change, THEN the plan SHALL show no changes. |

## Tags, names and configuration

| ID | Requirement |
|----|-------------|
| INF-TAG-1 | Every AWS provider block in every root SHALL set `default_tags` with exactly the PRD §14.1 / `terraform.md` tag set: `Project=graveyard`, `Env`, `Owner=olajide`, `ManagedBy=terraform`, `CostCentre=kiroween-2026`, `Repo=github.com/olajaido/graveyard`. |
| INF-TAG-2 | THE `Env` value SHALL be `dev` in `infra/envs/dev`, `prod` in `infra/envs/prod` and `shared` in `infra/bootstrap`. Tag values SHALL be set once per root in `locals` and not repeated on resources. |
| INF-TAG-3 | WHERE a resource type does not receive provider `default_tags`, or a service creates resources that do not inherit them, THE module SHALL pass the same tags explicitly. The design SHALL list any such resource. |
| INF-TAG-4 | THE `Project` and `Env` tag keys SHALL be active cost allocation tags, so that Budgets and Cost Explorer can filter by them; the budget and the monitor of INF-COST-1 and INF-COST-3 depend on `Project`. Activation is account-wide (F2), so: IF a key is already active, Graveyard SHALL NOT manage it at all (no Terraform resource for it, no import); Terraform SHALL activate only a key that is not active yet, with `lifecycle { prevent_destroy = true }`. The bootstrap root SHALL take the keys to activate from a variable `activate_cost_allocation_tag_keys` (a set, default empty, allowed values `Project` and `Env`). The runbook SHALL tell the maintainer to check the Billing console first and set the variable to the keys that are not yet active. Until `Project` is active the budget and the monitor read 0 (V7). |
| INF-NAME-1 | Every named AWS resource of an env root SHALL start with `graveyard-<env>-`. Account-level resources SHALL start with `graveyard-` and SHALL NOT start with `graveyard-dev-` or `graveyard-prod-`, except the two apply roles and two boundaries, which sit on an IAM path that the apply roles cannot touch (INF-APPLY-1). Modules SHALL receive the prefix as an input. |
| INF-CFG-1 | No `.tf`, `.tfvars`, `.tftest.hcl`, workflow, action or script file in the repo SHALL contain an AWS account ID, an ARN with an account ID, or an access key. ARNs SHALL be built from `data "aws_caller_identity"`, `data "aws_partition"` and `data "aws_region"` (PRD §14.1). The AWS documentation placeholder `123456789012` is allowed in test files only. |
| INF-CFG-2 | Every root SHALL set `allowed_account_ids` on the AWS provider from a variable supplied at run time (a GitHub Actions value in CI, a gitignored tfvars file for the maintainer), so that a run against the wrong account fails before any change. |
| INF-CFG-3 | Values that a later spec reads at runtime (model IDs, kill switch, limits) SHALL NOT be added here. They belong in SSM (`infra-serverless`). |
| INF-CFG-4 | Every variable SHALL have a `description` and a `type`. A variable with a closed set of values (env, region) SHALL have a `validation` block. |

## Region

| ID | Requirement |
|----|-------------|
| INF-REG-1 | THE default region of every root SHALL be eu-west-2, given as a variable whose validation allows only `eu-west-2`. |
| INF-REG-2 | THE plan role, the apply roles and the workload boundaries SHALL deny any action whose `aws:RequestedRegion` is not `eu-west-2`, except actions of global services (IAM, STS, CloudFront, WAF with CloudFront scope, ACM, Budgets, Cost Explorer), which are allowed in `us-east-1` too. |
| INF-REG-3 | THIS spec SHALL NOT create a `us-east-1` provider alias or an ACM certificate. It SHALL record in the design, for `infra-edge`, that the CloudFront certificate must be in us-east-1 and that the env roots will need an `aws.us_east_1` provider alias with the same `default_tags`. |

## GitHub OIDC and the roles

| ID | Requirement |
|----|-------------|
| INF-OIDC-1 | THE `github-oidc` module SHALL have an input `create_oidc_provider` (bool, default `false`). WHEN it is `false`, THE module SHALL create no OIDC provider and SHALL build the provider ARN as `arn:<partition>:iam::<account_id>:oidc-provider/token.actions.githubusercontent.com` from its `account_id` and `partition` inputs, for the trust policies. WHEN it is `true`, THE module SHALL create one IAM OIDC provider for `https://token.actions.githubusercontent.com` with the client ID (audience) `sts.amazonaws.com`, with `lifecycle { prevent_destroy = true }`. The bootstrap root SHALL pass the variable through with the same default. |
| INF-OIDC-2 | THE trust policy of every CI role SHALL allow only `sts:AssumeRoleWithWebIdentity` from that provider, with `StringEquals` (not `StringLike`) on `token.actions.githubusercontent.com:aud` = `sts.amazonaws.com` and on `token.actions.githubusercontent.com:sub`, each allowed subject listed in full. No wildcard SHALL appear in a subject. |
| INF-OIDC-3 | THE plan role trust SHALL allow exactly the subjects `repo:olajaido@102736714/graveyard@1443508961:pull_request` and `repo:olajaido@102736714/graveyard@1443508961:ref:refs/heads/main` (the immutable subject of this repository: owner and repository IDs included; the form without IDs is not trusted). |
| INF-OIDC-4 | THE `graveyard-dev-apply` trust SHALL allow exactly `repo:olajaido@102736714/graveyard@1443508961:environment:dev`. THE `graveyard-prod-apply` trust SHALL allow exactly `repo:olajaido@102736714/graveyard@1443508961:environment:prod`. |
| INF-OIDC-5 | THE repo owner and name SHALL be variables of the bootstrap root, so the subjects are built from them and not typed in several places. |
| INF-OIDC-6 | THE maximum session duration of every CI role SHALL be 1 hour. |
| INF-OIDC-7 | No IAM user, access key or long-lived AWS credential SHALL be created or stored in GitHub. |
| INF-OIDC-8 | WHEN a workflow assumes an apply role from a job with no environment, with the other env's environment, from a branch other than `main`, or from a fork, THE `AssumeRoleWithWebIdentity` call SHALL fail. This SHALL be checked once by hand and the result recorded in the bootstrap runbook. The check is deferred to the ship-week security review (PRD §16 W4) by maintainer decision of 18 Nov 2026; until then the policy tests and Access Analyzer stand in. |
| INF-OIDC-9 | THE workflows SHALL be triggered by `pull_request`, `push` and `workflow_call` only (plus `workflow_dispatch` where the design says so). No workflow SHALL use `pull_request_target`. A CI guard SHALL enforce this. |
| INF-OIDC-10 | THE system SHALL NOT import, adopt, read through a data source, modify or delete the OIDC provider that already exists in the shared account and is owned by another project. No `import` block, no `terraform import` and no data source for it SHALL exist, and the apply roles and the boundaries SHALL deny changes to it (INF-APPLY-1). The module relies on a fact checked by the maintainer on 18 Nov 2026 and not re-verified by the agent: the existing provider's client ID list includes `sts.amazonaws.com`. THE runbook SHALL say what to do if that stops being true (F3). |

### Plan role (read-only)

| ID | Requirement |
|----|-------------|
| INF-PLAN-1 | THE plan role SHALL have read actions only (`Describe*`, `Get*`, `List*` and the equivalents a refresh needs) on the services of INF-APPLY-2, through a customer-managed policy. It SHALL NOT use the AWS managed `ReadOnlyAccess` or `AdministratorAccess` policies. |
| INF-PLAN-2 | THE plan role SHALL NOT have `secretsmanager:GetSecretValue`, SHALL NOT have `kms:Decrypt` on any key other than the state key, and SHALL NOT have `s3:GetObject` on any bucket other than the state bucket. |
| INF-PLAN-3 | THE plan role's only write actions SHALL be: `s3:PutObject` and `s3:DeleteObject` on `envs/dev/terraform.tfstate.tflock` and `envs/prod/terraform.tfstate.tflock` (written by `use_lockfile = true` during plan), `s3:PutObject` on `plans/*`, and `kms:GenerateDataKey` and `kms:Encrypt` on the state key (needed to write those SSE-KMS objects). |
| INF-PLAN-4 | THE plan role SHALL read `envs/dev/terraform.tfstate` and `envs/prod/terraform.tfstate`, and SHALL NOT read `bootstrap/terraform.tfstate`. |

### Apply roles (least privilege, one per env)

| ID | Requirement |
|----|-------------|
| INF-APPLY-1 | Each apply role SHALL be able to create, update and delete the resources of its own env root only, and SHALL NOT be able to change any account-level resource: the state bucket configuration and policy, the state KMS key and its policy, the OIDC provider (whether or not this spec created it), the plan role, either apply role, either workload boundary, and the cost resources. This SHALL be enforced by explicit `Deny` statements on those ARNs. |
| INF-APPLY-2 | THE apply roles SHALL be limited to the AWS services of PRD §10.1 and §12: S3, CloudFront, WAFv2, ACM, API Gateway, Lambda, ECR, Step Functions, DynamoDB, Bedrock (guardrails and model access checks), Secrets Manager (secret containers, not values), SSM Parameter Store, KMS, IAM (as INF-APPLY-4…5), CloudWatch (logs, metrics, alarms, dashboards), CloudWatch Synthetics, SNS, X-Ray and EventBridge Scheduler. Any service a later spec adds SHALL be added by a reviewed change to the bootstrap root. |
| INF-APPLY-3 | WHERE an AWS service supports resource-level permissions, an apply role's statements SHALL be scoped to ARNs under its own env prefix (`graveyard-dev-` or `graveyard-prod-`, or the service's path equivalent). WHERE a service supports tag conditions instead, they SHALL require `Project` equal to `graveyard` and `Env` equal to the role's env, on create (`aws:RequestTag`) and on change (`aws:ResourceTag`). Every statement left with `Resource = "*"` SHALL be listed in the design with the AWS reason and carry an inline comment (`security.md`), and SHALL satisfy INF-SHARED-2. |
| INF-APPLY-4 | An apply role SHALL be able to create IAM roles only under its env's workload path and name prefix and only when `iam:PermissionsBoundary` equals its env's workload boundary ARN. It SHALL be able to attach or put policies only on those roles, and to pass roles (`iam:PassRole`) only on those roles and only to the services of INF-APPLY-2 (`iam:PassedToService`). |
| INF-APPLY-5 | THE apply roles SHALL NOT be able to create IAM users, groups, access keys, login profiles or OIDC/SAML providers, or to delete, change or detach a permissions boundary. |
| INF-APPLY-6 | Each apply role SHALL read and write only its own env's state key and `.tflock` key, SHALL read (`s3:GetObject`, `s3:GetObjectVersion`) only `plans/*`, and SHALL use the state key only through S3. |
| INF-APPLY-7 | Each workload boundary SHALL allow at most the actions of INF-APPLY-2 minus IAM, Budgets and Cost Explorer, limited to its env's resources as INF-APPLY-3 describes, and SHALL deny the regions of INF-REG-2. It SHALL satisfy INF-SHARED-1…4. Each workload role still gets its own narrower policy (PRD §13.2, written in `infra-serverless`). |

## Shared account (blast radius)

The account is shared with other projects. These requirements apply to every identity policy of the plan role and the apply roles, and to both workload boundaries.

| ID | Requirement |
|----|-------------|
| INF-SHARED-1 | EVERY write action allowed by a CI role policy or a workload boundary SHALL be limited by at least one of: (a) resource names that start with `graveyard-`, or IAM paths of the form `/graveyard-*/`, including the `/graveyard/<env>/` paths that `security.md` fixes for SSM parameters, Secrets Manager secrets and log groups; (b) a condition `aws:ResourceTag/Project` equal to `graveyard`; (c) on create, a condition `aws:RequestTag/Project` equal to `graveyard`. The tag key and value SHALL be written exactly as in the PRD §14.1 tag set (`Project`, `graveyard`). A write action is any action that is not `Get*`, `List*` or `Describe*`. |
| INF-SHARED-2 | THE `Resource = "*"` allow-list (every Allow statement that has `*` as a resource) SHALL contain only: (a) `List*`, `Describe*` and named metadata `Get*` actions; (b) creates that AWS requires to be on `*` and that carry the `aws:RequestTag/Project` condition of INF-SHARED-1(c); and (c) the approved exceptions of INF-SHARED-4. Writes to resources whose identifier AWS generates (KMS keys, distributions, certificates, HTTP APIs, guardrails) use an ARN pattern with the `aws:ResourceTag/Project` condition of INF-SHARED-1(b) and are not on the `*` list. Data-plane reads (`s3:GetObject*`, `dynamodb:GetItem`, `Query`, `Scan`, `ssm:GetParameter*`, `secretsmanager:GetSecretValue`, `kms:Decrypt`, `lambda:GetFunction*` and the like) SHALL NOT be on `*`. |
| INF-SHARED-3 | THE policies SHALL NOT allow any action that changes an account-wide setting or a resource of another project, including `iam:CreateServiceLinkedRole`, `iam:UpdateAccountPasswordPolicy`, `iam:CreateAccountAlias`, `s3:PutAccountPublicAccessBlock`, `logs:PutResourcePolicy`, `logs:CreateLogDelivery` and its related delivery actions, creating CloudFront cache policies or response-headers policies, `organizations:*` and `account:*`. A service-linked role that does not exist yet SHALL be created by the maintainer by hand, once (runbook). A later log-delivery need SHALL get its own reviewed exception in the spec that needs it. |
| INF-SHARED-4 | WHERE AWS offers no name, path or tag scoping for an action that a Graveyard workload or the apply roles need, THE action MAY be allowed only if it is on the fixed exception list approved by the maintainer on 18 Nov 2026 (design §5.2.7: E1 to E6), and the tests contain that list verbatim. A new exception needs a reviewed change to the bootstrap root and a new maintainer approval. |
| INF-SHARED-5 | THE `terraform test` files SHALL assert INF-SHARED-1…4 over the policy JSON of every CI role and boundary (INF-TEST-2): that each write Allow statement meets INF-SHARED-1, that the `*` allow-list equals a fixed list in the test and meets INF-SHARED-2, that none of the actions of INF-SHARED-3 is allowed, and that the exception list equals the design's. |
| INF-SHARED-6 | THE Bedrock exception E5 SHALL be limited to the exact inference-profile ARNs and the exact underlying foundation-model ARNs of the two PRD §10.2 profiles, with the profile IDs as module and root variables whose defaults are `eu.anthropic.claude-haiku-5-5` (narrate) and `eu.anthropic.claude-sonnet-5-5` (rites). It SHALL NOT use `eu-*` regions or `foundation-model/*`. The variables SHALL be validated to start with `eu.` (never `global.`, `security.md`). The foundation-model ARNs SHALL carry the condition `bedrock:InferenceProfileArn` equal to the profile's ARN. |


## CI and deploy workflows

| ID | Requirement |
|----|-------------|
| INF-CI-1 | `.github/workflows/ci.yml` SHALL run on `pull_request` and on `push` to `main`. Its Terraform jobs SHALL run WHEN a change touches `infra/**`, `.github/**`, `scripts/ci/**` or `docs/runbooks/**` (the tool-version file is under `infra/`), and SHALL be skipped otherwise. |
| INF-CI-2 | Both workflows SHALL set top-level `permissions: {}` and grant each job only what it needs. `id-token: write` SHALL be granted only to jobs that assume a role. |
| INF-CI-3 | THE static stage of `ci.yml` SHALL run, without AWS credentials, for all three roots and every module: `terraform fmt -check -recursive`; `terraform init -backend=false` and `terraform validate`; tflint with the AWS ruleset and a committed `.tflint.hcl`; checkov on `infra/` and `.github/workflows/`; actionlint; `terraform test` per module (INF-TEST-2); and the guards of INF-TEST-3. Any finding SHALL fail the job. |
| INF-CI-4 | A checkov or tflint check MAY be skipped only by an inline skip comment on the resource with a reason. No global skip list. |
| INF-CI-5 | WHEN the static stage passes, THE plan stage of `ci.yml` SHALL run `terraform plan -detailed-exitcode` for dev and for prod with the plan role, and SHALL write the plan text (with sensitive values redacted by Terraform and the account ID masked) to the job summary. It SHALL NOT post a PR comment. This is a recorded deviation from PRD §17.1 (O4, see "PRD deviations"). |
| INF-CI-6 | No plan file SHALL be uploaded as a workflow artifact. WHEN the trigger is a push to `main` and a plan has changes, THE plan job SHALL upload the binary plan to `s3://<state bucket>/plans/<run_id>/<env>.tfplan` with SSE-KMS and the state key, recording the commit SHA, run ID and env as object metadata, and SHALL pass the object's S3 version ID and SHA-256 to `deploy.yml` as job outputs. |
| INF-CI-7 | `deploy.yml` SHALL apply exactly the saved plan (`terraform apply <planfile>`), never a fresh plan. Before applying, THE apply job SHALL fetch the object by the version ID it was given and SHALL fail without applying IF the SHA-256 differs, IF the object's commit SHA differs from the commit being deployed, or IF the run ID or env metadata differ. IF the state changed after the plan was made, THEN Terraform's stale-plan check SHALL fail the apply. |
| INF-CI-8 | `deploy.yml` SHALL apply dev in the GitHub environment `dev` with `graveyard-dev-apply`, and prod in the GitHub environment `prod` with `graveyard-prod-apply`, only after the dev apply succeeded or was skipped because dev had no changes. WHEN an env's plan has no changes, its apply job SHALL be skipped. |
| INF-CI-9 | THE GitHub environment `prod` SHALL have a required reviewer, so the prod apply waits for a manual approval. Both environments SHALL restrict deployment branches to `main`. THE environments SHALL be set by hand by the maintainer from `docs/runbooks/github-environments.md`, not by Terraform (O1). |
| INF-CI-10 | WHEN the trigger is a pull request, `ci.yml` SHALL run the static stage and the plans and SHALL NOT upload a plan or call `deploy.yml`. WHEN the pull request comes from a fork or from Dependabot (no OIDC token), THE plan jobs SHALL be skipped with a notice, not fail. |
| INF-CI-11 | `deploy.yml` SHALL use a `concurrency` group per env with `cancel-in-progress: false`, so two applies to one env never overlap. |
| INF-CI-12 | THE workflows SHALL cache Terraform provider plugins with `TF_PLUGIN_CACHE_DIR` and `actions/cache`, keyed on the runner OS and the hash of all `.terraform.lock.hcl` files. A cache miss SHALL only slow the job. |
| INF-CI-13 | THE workflows SHALL assume roles with `aws-actions/configure-aws-credentials` pinned by SHA, with the account ID masked in logs. THE account ID SHALL be the GitHub Actions **repository secret** `AWS_ACCOUNT_ID`, so GitHub masks it and every ARN built from it (O3). It is not a credential, so INF-OIDC-7 still holds. |
| INF-CI-14 | No job SHALL print the AWS account ID, a role ARN or a state value to the log or the job summary in clear text. |
| INF-KIRO-1 | `ci.yml` SHALL have a job that runs on every pull request and push, independent of the path filter, and fails IF `.kiro/` or any tracked file under it is matched by a git ignore rule, or IF `.kiro/` has no tracked files (PRD §2.4, `structure.md` "Commit Hygiene"). The check SHALL have a test that shows it fails on a repo where `.kiro` is ignored. |

## Cost

| ID | Requirement |
|----|-------------|
| INF-COST-1 | THE bootstrap root SHALL create one monthly AWS Budgets cost budget for **Graveyard only**, not for the account: a cost filter `TagKeyValue` with the value `user:Project$graveyard` (the `Project` entry of the PRD §14.1 tag set, key and value exactly as written; tag filters are case-sensitive). It SHALL have email notifications on actual cost at 50%, 80% and 100% of the limit (PRD §12, `tech.md`) and on forecast cost at 100%. The budget counts only spend that carries the tag, and reads 0 until `Project` is an active cost allocation tag (INF-TAG-4, V7). |
| INF-COST-2 | THE budget limit SHALL be a variable with default amount `40` and unit `USD`. THE variable description and the runbook SHALL say to switch the unit to `GBP` (and the amount to 30) IF the account's billing currency is GBP. |
| INF-COST-3 | THE bootstrap root SHALL create a Cost Anomaly Detection monitor of type `CUSTOM` on the same `Project` tag (key `Project`, value `graveyard`), with `monitor_specification` built by `jsonencode` in `locals`, and a subscription that emails the subscribers when an anomaly's total impact is at least a configurable absolute amount, default `10` (USD, O2). It SHALL NOT create a `DIMENSIONAL`/`SERVICE` monitor. |
| INF-COST-4 | THE system SHALL NOT import, read, modify or delete any anomaly monitor or subscription that it did not create. The runbook SHALL contain no command that lists or imports the account's existing monitors. |
| INF-COST-5 | THE budget and the anomaly subscription SHALL notify email subscribers only, with the addresses from a variable that is not committed. No SNS topic and no dependency on `observability`. |
| INF-COST-6 | THE budget filter and the monitor specification SHALL take the tag key and value from one source in the bootstrap root's `locals`, the same source as the `Project` entry of `default_tags`, so they cannot drift apart. |

## Documentation

| ID | Requirement |
|----|-------------|
| INF-DOC-1 | `docs/runbooks/terraform-bootstrap.md` SHALL cover INF-BOOT-2…5, the shared-account checks of INF-OIDC-10 and INF-TAG-4, the one-off manual creation of any missing service-linked role (INF-SHARED-3), the hand checks of INF-OIDC-8 and INF-TEST-5 (deferred, see those requirements), and the accepted risk of O8: anyone who can push a branch can change `ci.yml` in a pull request and use the plan role, which reads dev and prod state and can write `plans/*`; only the maintainer can push, forks get no token, and the version-ID and SHA-256 check stops a written plan from being applied. |
| INF-DOC-2 | `docs/runbooks/github-environments.md` SHALL list the GitHub environment settings of INF-CI-9 and every GitHub variable and secret the workflows read, with names and where each value comes from, without the values. |
| INF-DOC-3 | `infra/README.md` SHALL explain the three roots, the state keys, the env prefixes, and how to run a local plan for dev. |
| INF-DOC-4 | The README "production hardening" note of PRD §10.3 (multi-account with Organizations, a separate prod account) SHALL say that the shared account, which other projects also use, is the part to split first, and that the IAM controls of INF-SHARED are a mitigation, not a replacement. |

## Verification

| ID | Requirement |
|----|-------------|
| INF-TEST-1 | `terraform fmt -check -recursive`, `terraform validate` on every root and module, tflint and checkov SHALL pass locally and in CI. |
| INF-POL-1 | Every IAM policy, trust policy, permissions boundary, KMS key policy and S3 bucket policy SHALL be built with `jsonencode()` in `locals`, never with `data "aws_iam_policy_document"`. Modules SHALL declare no `data` sources; the account ID and partition SHALL be module inputs, read by the roots from `data "aws_caller_identity"` and `data "aws_partition"`. So `terraform test` asserts the real policy JSON offline without mock data sources. A CI guard SHALL fail on a `data` block in `infra/modules/` or on `aws_iam_policy_document` anywhere in `infra/`. |
| INF-TEST-2 | Each module SHALL have `terraform test` files (`*.tftest.hcl`) that run offline (no AWS credentials, no backend, `mock_provider` with no mocked data sources) and assert at least: the state bucket settings of INF-STATE-1…3; the TLS-only and SSE-KMS bucket policy statements; the exact OIDC subjects and `StringEquals` of INF-OIDC-2…4; **both settings of `create_oidc_provider`** (with `false`: no provider resource, and the trust principal is the ARN built from `account_id` and `partition`; with `true`: one provider with the audience `sts.amazonaws.com`); the deny statements of INF-APPLY-1 and INF-APPLY-5; the boundary condition of INF-APPLY-4; the region denies of INF-REG-2; the INF-SHARED-1…5 checks; the budget filter, thresholds and the custom monitor specification of INF-COST-1, INF-COST-3 and INF-COST-6. The tests SHALL check the real policy JSON (INF-POL-1), and SHALL assert that every managed policy is at most 6,144 characters and no role has more than 10 managed policies. |
| INF-TEST-3 | Guards in CI SHALL fail IF any tracked file under `infra/`, `.github/`, `scripts/ci/` or `docs/runbooks/`, or any tracked `*.tf`, `*.tfvars*` or `*.hcl` file anywhere, contains a standalone 12-digit number (other than the allowed placeholder in test files) or an `arn:aws…:<12 digits>:` string; IF a `*.tfstate`, `*.tfplan`, `backend.hcl` or `*_override.tf` is tracked; IF a workflow uses `pull_request_target`; or IF a third-party action in `.github/` is not pinned by a 40-character SHA. Each guard SHALL have a bad-sample test so it cannot pass vacuously. |
| INF-TEST-4 | WHEN the bootstrap and env roots are applied, a second `terraform plan` on each SHALL report no changes. |
| INF-TEST-5 | (Deferred to the ship-week security review, PRD §16 W4.) THE hand checks of INF-OIDC-8, a check that the plan role cannot write outside `plans/*` and the lock keys, and a check that `graveyard-dev-apply` cannot change a `graveyard-prod-` resource or the prod state SHALL be run once and recorded in the runbook and the journal. |

---

## Decisions taken in review

Round 1 (18 Nov 2026). The first draft's conflicts C1–C8 are closed. The IDs stay because the design refers to them.

| ID | Conflict in the first draft | Decision | Applied in |
|----|-----------------------------|----------|------------|
| C1 | Tag key `Environment` (scope) against `Env` plus `Repo` (PRD §14.1, `terraform.md`) | Use the PRD / `terraform.md` tag set exactly. The scope's list was wrong. | INF-TAG-1, INF-TAG-2, INF-TAG-4 |
| C2 | Plan role on PRs against environment-only trust | Plan role trusts `…:pull_request` and `…:ref:refs/heads/main`. CI uses `pull_request`, never `pull_request_target`. No `secretsmanager:GetSecretValue`, no `kms:Decrypt` except the state key. Apply roles trust only `environment:dev` / `environment:prod`. | INF-OIDC-3, INF-OIDC-4, INF-OIDC-9, INF-PLAN-2 |
| C3 | One apply role for both envs | Two apply roles, `graveyard-dev-apply` and `graveyard-prod-apply`, each limited to its own name prefix and state key. | INF-APPLY-1…7, INF-CI-8 |
| C4 | One Terraform workflow against PRD `ci.yml` / `deploy.yml` | Follow the PRD: `ci.yml` (fmt, validate, tflint, checkov, `terraform test`, plan) and `deploy.yml` (apply, environment-gated, prod with a required reviewer). | INF-CI-1…11 |
| C5 | Plan artifact readable on a public repo | No workflow artifacts for plans. Plans go to the state bucket under `plans/<run_id>/`, SSE-KMS with the state key, expired after 7 days. Apply checks the plan's commit SHA. The plan role may write only `plans/*` and the `.tflock` keys. | INF-STATE-3, INF-PLAN-3, INF-CI-6, INF-CI-7 |
| C6 | Where cost resources live and how they notify | `infra/bootstrap` holds all account-level resources and is applied locally by the maintainer. Budget and anomaly monitor notify email subscribers, no SNS, no `observability` dependency. Add modules `state`, `github_oidc` (directory `github-oidc` per O6), `cost` and record the `structure.md` update. | INF-BOOT-1, INF-LAY-1, INF-LAY-5, INF-COST-5 |
| C7 | Bucket name and account ID | Random-suffix bucket name. `backend.hcl` gitignored locally. In CI the bucket name comes from a repository variable (not a secret). | INF-STATE-1, INF-STATE-7 |
| C8 | Budget currency | Budget amount is a variable, default USD 40, with a note to switch to GBP if the account bills in GBP. | INF-COST-2 |
| — | `.kiro` check had no owner | `ci.yml` fails if `.kiro/` is git-ignored. Owned by this spec. | INF-KIRO-1 |
| — | Existing services anomaly monitor | **Superseded by SA2.** The first-round decision to import an existing services monitor no longer applies. | INF-COST-3, INF-COST-4 |
| O1 | GitHub environments by hand or by Terraform | By hand from a runbook, as a MANUAL task. | INF-CI-9, INF-DOC-2 |
| O2 | Anomaly alert threshold | USD 10. | INF-COST-3 |
| O3 | `AWS_ACCOUNT_ID` as a repository secret | Agreed. | INF-CI-13 |
| O4 | Plan in the job summary, not a PR comment | Agreed, recorded as a PRD deviation. | INF-CI-5, "PRD deviations" |
| O5 | Version ID and SHA-256 check on saved plans | Agreed as designed. | INF-CI-6, INF-CI-7 |
| O6 | Module directory naming | Follow `structure.md`: hyphenated directories (`github-oidc`); labels in code may stay snake_case. | INF-LAY-1 |
| O7 | checkov and actionlint from images pinned by digest | Agreed. | INF-VER-4 |
| O8 | Plan role usable from a PR branch | Accept and document. | INF-DOC-1 |
| O9 | Synthetics canary name length | Add to "Belongs elsewhere" for `observability`. | Belongs elsewhere |
| R2 | Policy construction | Every IAM, trust, KMS and bucket policy is `jsonencode()` in `locals`, not `aws_iam_policy_document`. | INF-POL-1, INF-TEST-2 |
| A1 | Hand checks H1–H10 on the critical path | Deferred to the ship-week security review (PRD §16 W4); only the cost-tag activation stays in this spec. | INF-OIDC-8, INF-TEST-5, tasks T27 |
| A2 | Exercising the apply path | No test-only resource here. The first merge to `main` runs an output-only apply (the env roots' `name_prefix` output) through `deploy.yml`, which exercises the plumbing; the first resource-creating apply is `infra-serverless`'s. | INF-LAY-2, tasks "Report" |
| SA1 | Budget scope in a shared account | Filter the budget to Graveyard only with a cost filter on the `Project` cost allocation tag, key and value exactly as in the PRD §14.1 tag set (case-sensitive). It reads 0 until the tag is active (V7). | INF-COST-1, INF-TAG-4, INF-COST-6 |
| SA2 | Anomaly monitor in a shared account | A `CUSTOM` monitor on the same `Project` tag, `monitor_specification` as `jsonencode` in `locals`, not a `DIMENSIONAL`/`SERVICE` monitor. The import logic of INF-COST-4 is dropped. The account's existing monitors are never touched. | INF-COST-3, INF-COST-4 |
| SA3 | Existing GitHub OIDC provider | The account already has a provider for `token.actions.githubusercontent.com`, owned by another project, with `sts.amazonaws.com` in its client ID list (checked by the maintainer). New input `create_oidc_provider` (bool, default `false`): when `false`, no provider is created and the ARN is built from `account_id` and `partition`; the existing provider is never imported or managed. When `true`, one is created with `prevent_destroy`. Tests cover both settings. | INF-OIDC-1, INF-OIDC-10, INF-TEST-2 |
| SA4 | Blast radius in a shared account | Every write action of the CI roles and boundaries is limited to `graveyard-*` names, the `/graveyard-*/` IAM paths, or the `Project` tag (`aws:ResourceTag`, and `aws:RequestTag` on create). The `*` allow-list test may contain only read/list actions and AWS-required creates that carry a RequestTag condition. | INF-SHARED-1…5, INF-APPLY-3, INF-APPLY-7 |
| SA5 | Shared service quotas | Lambda concurrency and other service quotas are shared with other projects. `infra-serverless` sets reserved concurrency and does not assume the account quota. | "Belongs elsewhere" |
| F1–F7 | Round-3 flags | F1 accepted (`narrate` uses a `Project`-tagged application inference profile). F2: do not manage an already-active tag key; activate only inactive keys, with `prevent_destroy`. F3 accepted. F4: removals accepted; E6 added for CloudFront origin access controls; `infra-edge` uses AWS-managed cache and response-headers policies; missing service-linked roles created by hand once; later log-delivery needs get their own reviewed exception. F5: E1 to E5 approved, E5 limited to the exact PRD §10.2 profile and foundation-model ARNs (IDs as variables). F6: recorded as a PRD deviation. F7 agreed. | INF-TAG-4, INF-SHARED-2…4, INF-SHARED-6 |
| T6.3 | `override_resource` for unknown computed values in module tests | Approved (`random_id` hex and the KMS key ARN, `override_during = plan`). | INF-TEST-2 |
| — | Kept from the first draft | The permissions boundary, the lock-file writes for the plan role, the `allowed_account_ids` guard with the account-ID scan, and `terraform test` per module. | INF-APPLY-4, INF-PLAN-3, INF-CFG-2, INF-TEST-2, INF-TEST-3 |

Two additions followed from the round-1 decisions; the version-ID check was accepted in round 2 (O5):
- **Version ID and SHA-256 check on the plan (INF-CI-6, INF-CI-7).** The plan role can write any key under `plans/*`, and it can be used from a pull request. A commit-SHA check alone does not stop a PR job from overwriting a `main` run's plan with one that carries the right metadata. Passing the S3 version ID and SHA-256 through job outputs, which a PR job cannot change, closes that gap.
- **Plan role KMS writes (INF-PLAN-3).** Writing SSE-KMS lock and plan objects needs `kms:GenerateDataKey` (and `kms:Encrypt`, per the S3 backend documentation) on the state key.

---

## Flags raised in round 3 and the maintainer's decisions

Decided on 18 Nov 2026. The flag IDs stay because the design refers to them.

| ID | Flag | Where | Decision |
|----|------|-------|----------|
| F1 | **The budget and the monitor see only tagged spend.** Spend with no `Project` tag, or from something that cannot carry it, is outside both. Whether Bedrock on-demand token spend carries the tag is not verified. Tag attribution is not retroactive. | INF-COST-1, INF-COST-3 | **Accepted.** `narrate` SHALL use a `Project`-tagged application inference profile so Bedrock spend is attributed to Graveyard ("Belongs elsewhere"). The token caps stay the control until then. |
| F2 | **Cost allocation tag keys are account-wide.** Other projects may already use `Project` or `Env`. | INF-TAG-4 | **Decided.** If a key is already active, Graveyard does not manage it at all. Terraform activates only a key that is not active yet, with `prevent_destroy`. The runbook checks the Billing console first and sets `activate_cost_allocation_tag_keys` accordingly. |
| F3 | **The shared OIDC provider is owned by someone else.** If it is deleted or loses `sts.amazonaws.com`, CI stops and this spec cannot fix it. | INF-OIDC-10 | **Accepted.** |
| F4 | **The strict allow-list removes actions the first draft allowed:** `iam:CreateServiceLinkedRole`; the log-delivery actions and `logs:PutResourcePolicy`; creating CloudFront origin access controls, cache policies and response-headers policies; any create without RequestTag support. | INF-SHARED-3, design §5.2.3 | **Removals accepted, with two changes.** (1) `infra-edge` uses AWS-managed CloudFront cache and response-headers policies, so no create is needed ("Belongs elsewhere"). (2) Creating, reading, listing, updating and deleting origin access controls is allowed on `*` as exception **E6**, because they cannot be tagged or named (the maintainer's justification: AWS refuses to delete an OAC that is attached to a distribution). Missing service-linked roles are created by hand once (runbook). A later log-delivery need gets its own reviewed exception in the spec that needs it. |
| F5 | **Five actions cannot meet INF-SHARED-1 and INF-SHARED-2 as written:** E1 `xray:PutTraceSegments`, E2 `xray:PutTelemetryRecords`, E3 `cloudwatch:PutMetricData`, E4 `ecr:GetAuthorizationToken`, E5 `bedrock:InvokeModel`. | INF-SHARED-4, design §5.2.7 | **E1 to E5 approved verbatim, E5 narrowed:** exact inference-profile and foundation-model ARNs of the PRD §10.2 Haiku and Sonnet `eu.` profiles, profile IDs as variables with those defaults, not `eu-*` (INF-SHARED-6). E6 added by F4. The T9.0 gate is passed. |
| F6 | **PRD §10.3 and §2.4 say "personal AWS account".** | PRD deviations | **Recorded as a PRD deviation.** |
| F7 | **Two interpretations:** (1) read/list on `*` means `List*`, `Describe*` and a named list of metadata `Get*`; data-plane reads never on `*`. (2) The `/graveyard/<env>/` paths count as Graveyard names. | INF-SHARED-1, INF-SHARED-2 | **Agreed.** |

Residual risks the decisions leave, recorded so they are not forgotten:
- **E6 can touch other projects' origin access controls.** An unattached OAC of another project can be updated or deleted, and updating an attached one can change how its distribution signs requests. AWS refusing to delete an attached OAC limits only deletion.
- **E5 depends on the profile routing.** The two profiles route to seven EU regions (read by the maintainer from `list-inference-profiles` in eu-west-2, 18 Nov 2026; the IDs equal PRD §10.2). The foundation-model regions are a variable (`bedrock_foundation_model_regions`) whose default is exactly those seven, with no wildcard. If AWS adds a routing region later, InvokeModel is denied (it fails closed) until a reviewed bootstrap change adds it (V19).

---

## PRD deviations

| Deviation | PRD says | This spec | Decision |
|-----------|----------|-----------|----------|
| Plan output on pull requests | §17.1: `tf plan (dev+prod, PR comment)` | Job summary only, no PR comment (INF-CI-5) | O4 |
| AWS account | §10.3 and §2.4: "the same personal AWS account", "personal accounts" | The account is shared with other projects. Budget and anomaly monitor are filtered to the `Project` tag, the OIDC provider is reused, and every CI write is limited to Graveyard names or tags (INF-COST-1, INF-OIDC-1, INF-SHARED) | SA1–SA4, F6 |
| Apply roles | §17.1: "an apply role restricted to `main` and the `prod` environment" | One apply role per env, each trusted only from the GitHub environment of the same name; both environments limited to `main` (INF-OIDC-4, INF-CI-9) | C3 |
| Bootstrap contents | §14: "state bucket (S3 native locking), OIDC role" | All account-level resources, including the budget and anomaly monitor (INF-BOOT-1) | C6 |

The PRD, `structure.md` and `terraform.md` text is updated by a task (INF-LAY-5, design §11).

---

## Belongs elsewhere

| Item | Belongs in | Why not here |
|------|------------|--------------|
| Lambdas (`publish = true`, `live` alias), Step Functions, DynamoDB table, app KMS CMK, artefact and upload buckets, ECR repo for the Syft image | `infra-serverless` | Application resources. This spec only gives the apply roles the right to create them. Their names must start with `graveyard-<env>-`; PRD §10.4 calls the table `graveyard`, so `infra-serverless` must name it with the env prefix (for example `graveyard-dev-main`). |
| One role per Lambda with the policies of PRD §13.2, under the workload path with the workload boundary | `infra-serverless` | This spec defines the boundary and the apply roles' limits on role creation (INF-APPLY-4, INF-APPLY-7). |
| SSM parameters (model IDs, kill switch, limits) and Secrets Manager secrets for the two GitHub Apps | `infra-serverless` (containers), `github-app-pull-requests` (the apps and their keys) | Runtime config and secrets. Secret values are put in by hand, never through Terraform state. |
| Bedrock Guardrail and model-access IAM | `infra-serverless` / `narrate` | Needs the inference-profile ARNs from SSM. |
| CloudFront, WAF, OAC, security headers, static site bucket | `infra-edge` | Edge resources. |
| ACM certificate in us-east-1 and the `aws.us_east_1` provider alias | `infra-edge` | Recorded by INF-REG-3. The region rule of INF-REG-2 already allows ACM in us-east-1. |
| Domain and DNS (Route 53 or other) | `infra-edge` | No domain decision in the PRD. Route 53 is not in INF-APPLY-2 until it is decided. |
| SNS alarm topic, all alarms of PRD §12.1, Synthetics canary, dashboards, log retention, custom metrics | `observability` | Budget and anomaly alerts are email-only by decision C6. If `observability` later wants them on its topic, that is a change to the `cost` module in the bootstrap root. |
| Application jobs of `ci.yml` (lint, unit, property, integration, eval) and of `deploy.yml` (build, contract and e2e on dev, alias shift, smoke test) | the specs that own that code; PRD §17.1 | This spec creates both files with the Terraform jobs and the `.kiro` check. Later specs add jobs to them. |
| GitHub branch protection, push protection, Dependabot settings | repo settings, PRD §13 T6, T8 | Not Terraform. Environment settings are covered by INF-CI-9 and INF-DOC-2. |
| Multi-account split (Organizations, separate prod account) | README "production hardening" (PRD §10.3) | Not built. INF-DOC-4 points at it. |
| **Lambda concurrency and other service quotas** (account concurrency, API Gateway and Step Functions request rates, Bedrock and CloudFront quotas, IAM role and policy counts) | `infra-serverless` (and `infra-edge` for edge quotas) | These quotas are shared with other projects, so a spike elsewhere can throttle Graveyard and the reverse. `infra-serverless` SHALL set **reserved concurrency** on every function, sized from the PRD §12 target of 20 concurrent scans, and SHALL NOT assume the account quota. Reserved concurrency also comes out of the account's unreserved pool, so it must be checked against what other projects use. The apply roles allow `lambda:PutFunctionConcurrency` on `function:graveyard-<env>-*` for this (SA5). |
| Service-linked roles | the maintainer, by hand, once | Missing service-linked roles are created by the maintainer with `aws iam create-service-linked-role` (runbook, INF-SHARED-3). The CI roles never create one. |
| Log delivery (WAF and API Gateway access logs, Step Functions logging) and account-wide log resource policies | the spec that needs it | Each gets its own reviewed exception in that spec (INF-SHARED-3, F4). |
| **CloudFront cache policies and response-headers policies** | `infra-edge` | `infra-edge` uses the AWS-managed policies and creates none (INF-SHARED-3). **Check in that spec:** PRD §14.1 and `terraform.md` require a response-headers policy with CSP and `frame-ancestors none`; I believe the AWS-managed security-headers policy has no CSP (not verified), in which case `infra-edge` must add the CSP another way, for example in a CloudFront function named `graveyard-<env>-*`, which the apply roles may manage. Origin access controls are allowed by exception E6. |
| **Bedrock cost attribution (F1)** | `narrate` / `infra-serverless` | `narrate` SHALL call Bedrock through a `Project`-tagged application inference profile, so Bedrock spend appears under the `Project` tag filter of the budget and the monitor. When it does, the boundary's exception E5 is extended in a reviewed bootstrap change to the application inference profile's ARN with `aws:ResourceTag/Project` equal to `graveyard`, which is no longer an exception. Until then the token caps are the control. |
| **No streaming from `narrate` and `rites` (V20)** | `narrate` / `rites` / `infra-serverless` | The workload boundary exempts only `bedrock:InvokeModel` (through the two approved profiles) from the region deny, so `bedrock:InvokeModelWithResponseStream` is denied whenever Bedrock routes it outside eu-west-2. `narrate` and `rites` SHALL use the non-streaming call (`InvokeModel`; check in `infra-serverless` which IAM action `Converse` needs before using it), not `InvokeModelWithResponseStream` or `ConverseStream`. The first live call confirms V20; if the application inference profile of F1 is adopted, the exempt profile ARNs change with it. |
| Synthetics canary names are limited to 21 characters; `graveyard-prod-` uses 15, leaving 6 | `observability` | Canaries are not created here. The env prefix rule (INF-NAME-1) still applies, so `observability` must choose names of at most 6 characters after the prefix, or record a deviation. |
| Vigil and the dogfood hook on our own dependencies | `vigil-action`, `kiro-power` | Terraform providers are not npm or PyPI packages. |

## Amendment A1 (19 Nov 2026, maintainer-approved, made by spec `scan-backend` task T0)
Three changes to the apply roles and the workload boundaries, for `scan-backend`. The bootstrap root is applied by the maintainer.
| ID | Change |
|----|--------|
| A1-1 | **KMS grants.** Each apply role gets `kms:CreateGrant` (statement `KmsCreateGrant`, in the data policy) on `key/*` only with the `Project` and `Env` resource tags of INF-APPLY-3 **and** `Bool kms:GrantIsForAWSResource = true`. The boundaries do not get it. |
| A1-2 | **Exception E7.** The CloudWatch Logs log-delivery actions `logs:CreateLogDelivery`, `GetLogDelivery`, `UpdateLogDelivery`, `DeleteLogDelivery`, `ListLogDeliveries`, `DescribeResourcePolicies`, `DescribeLogGroups` on `*` (AWS has no resource-level permissions for them): statement `ExceptionE7` in the apply `ops` policy of each env and in each boundary. Reason: Step Functions execution logs and API Gateway access logs. `logs:PutResourcePolicy` stays forbidden; if the first run shows it is needed, that is a new exception (INF-SHARED-4). INF-SHARED-3 no longer lists the three `*LogDelivery` actions; its other entries stand. The approved exceptions are now E1 to E7. |
| A1-3 | **Express executions.** Each boundary gets `states:DescribeExecution` and `states:StopExecution` on `arn:<p>:states:<r>:<a>:express:graveyard-<env>-*` (statement `StatesExpressExecutions`), for the Express child executions of a Distributed Map. |
Tests: `tests/shared_account.tftest.hcl` (E7 in the exception and star lists, the removed-actions list), `tests/boundary.tftest.hcl` (E7 and the Express statement, exactly), `tests/services.tftest.hcl` (E4, E6 and E7; `KmsCreateGrant`, exactly, and only in the apply data policies).

## Amendment A2 (20 Nov 2026, maintainer-requested after the failed apply-dev of run 44828393001, made by spec `scan-backend`)
The first scan-backend apply stopped on three permission gaps of the apply roles. A2 closes them and the gaps the audit in `.kiro/specs/scan-backend/design.md` §14 found. The bootstrap root is applied by the maintainer.
| ID | Change |
|----|--------|
| A2-1 | **Exception E9: API Gateway tags.** Each apply role's edge policy gets `apigateway:POST`, `apigateway:GET`, `apigateway:DELETE` on `arn:<p>:apigateway:<r>::/tags/*` (statement `ExceptionE9`). The Service Authorization Reference (read 20 Nov 2026) lists only `aws:RequestTag/${TagKey}` and `aws:TagKeys` for the **PUT** action on the `Tags` resource of API Gateway V1, and no request-tag key for POST on `/tags/*` in API Gateway V2, so no tag condition is set. The resource is limited to the tags path of this region. |
| A2-2 | **KMS through services.** Each apply role's data policy gets `kms:Decrypt`, `kms:Encrypt`, `kms:GenerateDataKey`, `kms:GenerateDataKeyWithoutPlaintext`, `kms:ReEncryptFrom`, `kms:ReEncryptTo`, `kms:DescribeKey` on `key/*` (statement `KmsUseViaServices`), with `aws:ResourceTag/Project = graveyard`, `aws:ResourceTag/Env = <env>` and `kms:ViaService` in `dynamodb`, `secretsmanager` and `s3` of eu-west-2. Wildcards (`GenerateDataKey*`, `ReEncrypt*`) are spelled out, because no Allow action may hold a wildcard (INF-SHARED-1). No env resource uses the app key with Lambda, Step Functions, Logs or SNS, so those services are not listed. |
| A2-3 | **Exception E8: state machine validation.** `states:ValidateStateMachineDefinition` on `*` (no resource-level permission; it validates a document and changes nothing). The Terraform provider calls it on every plan and apply that changes a definition, so both the apply compute policies and the plan role's compute read policy get statement `ExceptionE8`. |
| A2-4 | **Small additions found by the audit.** `s3:TagResource` (tag-on-create of a bucket; without it the provider retries without tags and then calls `PutBucketTagging`) on the env's bucket names; `kms:UpdateAlias` and `kms:DeleteAlias` on the key side of an alias (an alias change or delete needs the permission on the key too). |
| A2-5 | **The workload boundaries are not widened.** The apply roles have no permissions boundary; `graveyard-<env>-boundary` caps only the workload roles that Terraform creates. Adding the apply-only statements of A2-1 to A2-3 to it would let a Lambda function manage API Gateway or re-encrypt with the app key, so it is left as it is. Its `KmsUse` statement already allows the `kms:Decrypt`, `kms:GenerateDataKey` and `kms:DescribeKey` calls that DynamoDB, Secrets Manager and S3 make for the functions. A test asserts both points. |
The approved exceptions are now E1 to E9.
