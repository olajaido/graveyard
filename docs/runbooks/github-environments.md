# Runbook: GitHub environments, variables and the secret

Set by hand, once, after the bootstrap apply (`docs/runbooks/terraform-bootstrap.md`). These are repository settings,
not Terraform: managing them from Terraform would need a long-lived repository-admin token, which this project avoids
(decision O1). Nothing here is an AWS credential.

## 1. Repository variables and secret

Settings, Secrets and variables, Actions. All four are **repository level**, because the plan jobs have no
environment and must read them too (no environment-level secrets or variables).

| Name | Kind | Where the value comes from | Why this kind |
|------|------|----------------------------|---------------|
| `TF_STATE_BUCKET` | variable | output `state_bucket_name` of `infra/bootstrap` | A name with a random suffix and no account ID: not a secret (decision C7). |
| `TF_STATE_KMS_KEY_ID` | variable | output `state_kms_key_id` (the key's UUID) | Contains no account ID. The workflows build the ARN from it and the secret below. |
| `AWS_REGION` | variable | `eu-west-2` | The only allowed region. |
| `AWS_ACCOUNT_ID` | **secret** | your 12-digit account ID | A secret only so that GitHub masks it in every log line, and every ARN built from it. It is not a credential (decision O3). Never make it a variable. |

The workflows read exactly these four names and no other secret. There is no AWS access key anywhere: CI assumes roles
through OIDC (INF-OIDC-7).

## 2. Environments

Settings, Environments, New environment.

| Environment | Deployment branches and tags | Required reviewers | Prevent self-review | Wait timer |
|-------------|------------------------------|--------------------|---------------------|------------|
| `dev` | Selected branches and tags: `main` only | none | not applicable | 0 |
| `prod` | Selected branches and tags: `main` only | `olajaido` | **off**: the maintainer is the only reviewer, so turning it on would block every prod apply | 0 |

Why the names matter: the apply roles trust exactly the subjects `repo:olajaido/graveyard:environment:dev` and
`repo:olajaido/graveyard:environment:prod`, so a job can assume `graveyard-dev-apply` or `graveyard-prod-apply` only
when it runs in the environment of the same name. The deployment-branch rule is what limits that to `main`.

## 3. Check it

1. Settings, Environments: both exist, `main` is the only deployment branch, `prod` lists you as required reviewer.
2. Settings, Secrets and variables, Actions: the three variables and the one secret, and nothing else that looks like a
   credential.
3. The first pull request (`docs/runbooks/terraform-bootstrap.md`, results): the plan jobs are green and show "No
   changes" for both envs, and the summary and logs show `***` or `<account>` where the account ID would be.

## 4. What is not covered here

Branch protection, push protection and Dependabot settings are repository settings outside Terraform and outside this
spec (PRD section 13, T6 and T8). The hand checks of the roles are deferred to the ship-week security review
(`terraform-bootstrap.md`, section 13).
