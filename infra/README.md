# infra

Terraform for Graveyard. Spec: `.kiro/specs/infra-foundation/`.

## Roots and state

| Root | State key | Applied by |
|---|---|---|
| `bootstrap/` | `bootstrap/terraform.tfstate` (local state first, then migrated) | A maintainer, locally, once |
| `envs/dev/` | `envs/dev/terraform.tfstate` | CI (`deploy.yml`) |
| `envs/prod/` | `envs/prod/terraform.tfstate` | CI (`deploy.yml`), after approval |

Modules live in `modules/` (`state`, `github-oidc`, `cost`, `data`, `github-app`, `lambda-function`, `workflow`, `api`, `observability`, and the edge: `edge-cert`, `edge-waf`, `edge-site`, `edge-api`, `edge-alarms`). Module directories are hyphenated, resource labels may be snake_case. Modules contain no data sources. Policies are built with `jsonencode` in `locals`.

The hosted zone for `lastrites.dev` is made by hand and is never created, imported or read by Terraform: the edge modules write records into it by its ID (`route53_zone_id`, from the repository variable `ROUTE53_ZONE_ID`; a guard fails on any `aws_route53_zone`). The edge is described in `.kiro/specs/infra-edge/` and operated by `docs/runbooks/edge.md`.

All resource names start with `graveyard-<env>-` (or `graveyard/<env>/` for SSM and Secrets Manager).

## Shared account rules

The AWS account is shared with other projects. Every write permission in the CI roles is limited to one of:

- a `graveyard-` or `graveyard/` name prefix;
- `aws:ResourceTag/Project=graveyard` (and `Env`), or `aws:RequestTag` on create;
- an approved exception (E1 to E12, listed in the design).

Never widen a role to `*` without adding an exception to the spec first.

## Local work

Run everything through the pinned-image wrapper. It needs only Docker and does not read host AWS config or environment.

```
scripts/ci/local-checks.sh all          # fmt, validate, test, tflint, checkov, actionlint, guards
scripts/ci/local-checks.sh test         # offline terraform tests (mocked providers)
scripts/ci/local-checks.sh lock DIR     # init -backend=false, then providers lock
python3 -m unittest discover -s scripts/ci/tests
```

Agents and CI checks never run `init` against a real backend, `plan` or `apply` locally. Those steps are in `docs/runbooks/terraform-bootstrap.md` and run on a maintainer's machine or in the deploy workflow.

Tool versions are pinned in `.tool-versions`. Provider versions are exact (`aws = 6.73.0`, `random = 3.9.1`) with lock files for `darwin_arm64`, `linux_amd64` and `linux_arm64`.

## Runbooks

- `docs/runbooks/terraform-bootstrap.md`: first apply and state migration.
- `docs/runbooks/github-environments.md`: GitHub environments, protection rules, variables.
