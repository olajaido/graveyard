# Apply roles, part 1: trust, state access, IAM statements and the explicit denies
# (INF-OIDC-4, INF-APPLY-1, INF-APPLY-4..6, INF-REG-2, decision C3). Offline; real policy JSON.

mock_provider "aws" {}

variables {
  account_id        = "123456789012"
  partition         = "aws"
  repo_owner        = "olajaido"
  repo_name         = "graveyard"
  state_bucket_name = "graveyard-tfstate-abcd1234"
  state_kms_key_arn = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
}

run "each_apply_role_trusts_exactly_its_own_environment" {
  command = plan

  assert {
    condition     = toset(keys(aws_iam_role.apply)) == toset(["dev", "prod"])
    error_message = "There must be one apply role per env."
  }

  assert {
    condition     = aws_iam_role.apply["dev"].name == "graveyard-dev-apply" && aws_iam_role.apply["prod"].name == "graveyard-prod-apply"
    error_message = "The apply roles must be graveyard-dev-apply and graveyard-prod-apply."
  }

  assert {
    condition     = alltrue([for e, r in aws_iam_role.apply : r.path == "/graveyard-ci/" && r.max_session_duration == 3600])
    error_message = "Apply roles must sit on the CI path and last one hour."
  }

  assert {
    condition = (
      jsondecode(aws_iam_role.apply["dev"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:olajaido/graveyard:environment:dev" &&
      jsondecode(aws_iam_role.apply["prod"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:olajaido/graveyard:environment:prod"
    )
    error_message = "Each apply role must trust exactly its own environment subject."
  }

  assert {
    condition = alltrue([
      for e, r in aws_iam_role.apply : (
        length(jsondecode(r.assume_role_policy).Statement) == 1 &&
        keys(jsondecode(r.assume_role_policy).Statement[0].Condition) == ["StringEquals"] &&
        jsondecode(r.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com" &&
        jsondecode(r.assume_role_policy).Statement[0].Action == "sts:AssumeRoleWithWebIdentity" &&
        jsondecode(r.assume_role_policy).Statement[0].Principal.Federated == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" &&
        !can(regex("[*?]", jsondecode(r.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]))
      )
    ])
    error_message = "Apply trust must be one StringEquals statement on the audience and the subject, with no wildcard."
  }

  assert {
    condition     = jsondecode(aws_iam_role.apply["dev"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] != jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]
    error_message = "The apply and plan roles must not share a subject."
  }
}

run "each_apply_role_has_its_core_policies_and_stays_under_the_attachment_limit" {
  command = plan

  assert {
    condition = toset([for k, p in aws_iam_policy.ci : k if startswith(k, "graveyard-dev-apply-")]) == toset([
      "graveyard-dev-apply-state", "graveyard-dev-apply-iam", "graveyard-dev-apply-compute", "graveyard-dev-apply-data",
      "graveyard-dev-apply-edge", "graveyard-dev-apply-ops", "graveyard-dev-apply-guard",
    ])
    error_message = "Unexpected dev apply policies."
  }

  assert {
    condition     = length([for k, a in aws_iam_role_policy_attachment.apply : k if startswith(k, "dev/")]) <= 10 && length([for k, a in aws_iam_role_policy_attachment.apply : k if startswith(k, "prod/")]) <= 10
    error_message = "A role can have at most 10 managed policies."
  }

  assert {
    condition     = alltrue([for k, p in aws_iam_policy.ci : length(p.policy) <= 6144])
    error_message = "A managed policy must be at most 6,144 characters."
  }
}

run "state_access_is_limited_to_the_own_env" {
  command = plan

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-state"].policy).Statement : s
      if s.Sid == "OwnStateKey"
      ][0] == {
      Sid      = "OwnStateKey"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject"]
      Resource = ["arn:aws:s3:::graveyard-tfstate-abcd1234/envs/dev/terraform.tfstate"]
    }
    error_message = "The dev role must read and write only the dev state key."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-state"].policy).Statement : s
      if s.Sid == "OwnLockKey"
      ][0] == {
      Sid      = "OwnLockKey"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      Resource = ["arn:aws:s3:::graveyard-tfstate-abcd1234/envs/prod/terraform.tfstate.tflock"]
    }
    error_message = "The prod role must use only the prod lock key."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-state"].policy).Statement : s
      if s.Sid == "ReadOwnPlans"
    ][0].Resource == ["arn:aws:s3:::graveyard-tfstate-abcd1234/plans/*/dev.tfplan"]
    error_message = "The dev role may read only dev plans."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : !anytrue(flatten([
        for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-state"].policy).Statement : [
          for a in flatten([s.Action]) : a == "s3:PutObject" && contains(flatten([s.Resource]), "arn:aws:s3:::graveyard-tfstate-abcd1234/plans/*")
        ]
      ]))
    ])
    error_message = "Apply roles must not write plans."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : [
        for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-state"].policy).Statement : s
        if s.Sid == "UseStateKey"
        ][0] == {
        Sid      = "UseStateKey"
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource = ["arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"]
        Condition = {
          StringEquals = {
            "kms:ViaService"          = "s3.eu-west-2.amazonaws.com"
            "aws:ResourceTag/Project" = "graveyard"
          }
        }
      }
    ])
    error_message = "State key use must be four actions, through S3, on a key tagged Project=graveyard."
  }
}

run "role_creation_needs_the_env_boundary_and_the_env_path" {
  command = plan

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-iam"].policy).Statement : s
      if s.Sid == "CreateWorkloadRoles"
      ][0] == {
      Sid      = "CreateWorkloadRoles"
      Effect   = "Allow"
      Action   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
      Resource = ["arn:aws:iam::123456789012:role/graveyard-dev/graveyard-dev-*"]
      Condition = {
        StringEquals = { "iam:PermissionsBoundary" = "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary" }
      }
    }
    error_message = "The dev role may create only dev workload roles, and only with the dev boundary."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-iam"].policy).Statement : s
      if s.Sid == "CreateWorkloadRoles"
    ][0].Condition.StringEquals["iam:PermissionsBoundary"] == "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-prod-boundary"
    error_message = "The prod role must require the prod boundary."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-iam"].policy).Statement : s
      if s.Sid == "AttachOnlyOwnPolicies"
      ][0] == {
      Sid      = "AttachOnlyOwnPolicies"
      Effect   = "Allow"
      Action   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      Resource = ["arn:aws:iam::123456789012:role/graveyard-dev/graveyard-dev-*"]
      Condition = {
        ArnLike = { "iam:PolicyARN" = "arn:aws:iam::123456789012:policy/graveyard-dev/graveyard-dev-*" }
      }
    }
    error_message = "Only the env's own policies may be attached, never an AWS managed policy."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-iam"].policy).Statement : s
      if s.Sid == "PassWorkloadRoles"
      ][0] == {
      Sid      = "PassWorkloadRoles"
      Effect   = "Allow"
      Action   = ["iam:PassRole"]
      Resource = ["arn:aws:iam::123456789012:role/graveyard-dev/graveyard-dev-*"]
      Condition = {
        StringEquals = { "iam:PassedToService" = ["lambda.amazonaws.com", "states.amazonaws.com", "scheduler.amazonaws.com", "apigateway.amazonaws.com", "synthetics.amazonaws.com"] }
      }
    }
    error_message = "PassRole must be limited to the env's workload roles and to the five services."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : alltrue(flatten([
        for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-iam"].policy).Statement : [
          for r in flatten([s.Resource]) : strcontains(r, "/graveyard-${e}/graveyard-${e}-")
        ]
      ]))
    ])
    error_message = "Every IAM statement must name only the env's own role or policy path and prefix."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : !anytrue(flatten([
        for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-iam"].policy).Statement : [
          for a in flatten([s.Action]) : contains(["iam:CreateUser", "iam:CreateGroup", "iam:CreateAccessKey", "iam:CreateLoginProfile", "iam:CreateOpenIDConnectProvider", "iam:CreateSAMLProvider", "iam:DeleteRolePermissionsBoundary", "iam:DeleteUserPermissionsBoundary"], a)
        ]
      ]))
    ])
    error_message = "The apply roles must not be able to create users, keys, providers, or remove a boundary."
  }
}

run "the_guard_denies_ci_identity_state_config_the_other_env_and_cost" {
  command = plan

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-guard"].policy).Statement : s
      if s.Sid == "DenyCiIdentity"
      ][0] == {
      Sid    = "DenyCiIdentity"
      Effect = "Deny"
      Action = ["iam:*"]
      Resource = [
        "arn:aws:iam::123456789012:role/graveyard-ci/*",
        "arn:aws:iam::123456789012:policy/graveyard-ci/*",
        "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com",
      ]
    }
    error_message = "CI roles, CI policies and the OIDC provider must be denied to the apply role."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-guard"].policy).Statement : s
      if s.Sid == "DenyStateConfig"
      ][0] == {
      Sid      = "DenyStateConfig"
      Effect   = "Deny"
      Action   = ["s3:PutBucket*", "s3:DeleteBucket*", "s3:PutLifecycleConfiguration", "s3:PutEncryptionConfiguration", "s3:PutBucketPolicy", "s3:DeleteObjectVersion"]
      Resource = ["arn:aws:s3:::graveyard-tfstate-abcd1234", "arn:aws:s3:::graveyard-tfstate-abcd1234/*"]
    }
    error_message = "State bucket configuration must be denied."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-guard"].policy).Statement : s
      if s.Sid == "DenyOtherState"
      ][0].Resource == [
      "arn:aws:s3:::graveyard-tfstate-abcd1234/bootstrap/*",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/prod/*",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/plans/*/prod.tfplan",
    ]
    error_message = "The dev role must be denied bootstrap and prod state and plans."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-guard"].policy).Statement : s
      if s.Sid == "DenyOtherState"
      ][0].Resource == [
      "arn:aws:s3:::graveyard-tfstate-abcd1234/bootstrap/*",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/dev/*",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/plans/*/dev.tfplan",
    ]
    error_message = "The prod role must be denied bootstrap and dev state and plans."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-guard"].policy).Statement : s
      if s.Sid == "DenyStateKeyAdmin"
      ][0] == {
      Sid       = "DenyStateKeyAdmin"
      Effect    = "Deny"
      NotAction = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
      Resource  = ["arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"]
    }
    error_message = "Every other KMS action on the state key must be denied."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-guard"].policy).Statement : s if s.Sid == "DenyOtherEnv"][0].Resource == ["arn:aws:*:*:*:*graveyard-prod-*", "arn:aws:*:*:*:*graveyard/prod/*"] &&
      [for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-guard"].policy).Statement : s if s.Sid == "DenyOtherEnv"][0].Resource == ["arn:aws:*:*:*:*graveyard-dev-*", "arn:aws:*:*:*:*graveyard/dev/*"]
    )
    error_message = "Each apply role must be denied every resource named for the other env."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-guard"].policy).Statement : s if s.Sid == "DenyOtherEnvTag"][0].Condition == { StringEquals = { "aws:ResourceTag/Env" = ["prod"] } } &&
      [for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-guard"].policy).Statement : s if s.Sid == "DenyOtherEnvTag"][0].Condition == { StringEquals = { "aws:ResourceTag/Env" = ["dev"] } }
    )
    error_message = "Each apply role must be denied every resource tagged for the other env."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : (
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-guard"].policy).Statement : s if s.Sid == "DenyCost"][0].Action == ["budgets:*", "ce:*"] &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-guard"].policy).Statement : s if s.Sid == "DenySecretValues"][0].Action == ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"] &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-guard"].policy).Statement : s if s.Sid == "DenyIdentityCreation"][0].Resource == "*"
      )
    ])
    error_message = "Cost, secret values and identity creation must be denied."
  }
}

run "the_region_deny_is_in_both_apply_guards" {
  command = plan

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : (
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-guard"].policy).Statement : s if s.Sid == "DenyOutsideRegion"][0] == {
          Sid       = "DenyOutsideRegion"
          Effect    = "Deny"
          NotAction = ["iam:*", "sts:*", "cloudfront:*", "wafv2:*", "acm:*", "budgets:*", "ce:*", "s3:ListAllMyBuckets", "s3:GetBucketLocation"]
          Resource  = "*"
          Condition = { StringNotEquals = { "aws:RequestedRegion" = "eu-west-2" } }
        } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-guard"].policy).Statement : s if s.Sid == "DenyGlobalOutsideUsEast1"][0] == {
          Sid       = "DenyGlobalOutsideUsEast1"
          Effect    = "Deny"
          Action    = ["cloudfront:*", "wafv2:*", "acm:*"]
          Resource  = "*"
          Condition = { StringNotEquals = { "aws:RequestedRegion" = ["eu-west-2", "us-east-1"] } }
        }
      )
    ])
    error_message = "Both region denies must be in both apply guards."
  }
}

run "an_env_policy_never_names_the_other_env_outside_a_deny" {
  command = plan

  assert {
    condition = !anytrue(flatten([
      for k, p in aws_iam_policy.ci : [
        for s in jsondecode(p.policy).Statement : [
          for r in flatten([try(s.Resource, [])]) : strcontains(r, "prod")
        ]
        if s.Effect == "Allow"
      ]
      if startswith(k, "graveyard-dev-apply-")
    ]))
    error_message = "A dev apply policy must not allow anything named for prod."
  }

  assert {
    condition = !anytrue(flatten([
      for k, p in aws_iam_policy.ci : [
        for s in jsondecode(p.policy).Statement : [
          for r in flatten([try(s.Resource, [])]) : strcontains(r, "dev")
        ]
        if s.Effect == "Allow"
      ]
      if startswith(k, "graveyard-prod-apply-")
    ]))
    error_message = "A prod apply policy must not allow anything named for dev."
  }
}

run "apply_allows_never_use_a_wildcard_action" {
  command = plan

  assert {
    condition = !anytrue(flatten([
      for k, p in aws_iam_policy.ci : [
        for s in jsondecode(p.policy).Statement : [
          for a in flatten([try(s.Action, [])]) : strcontains(a, "*")
        ]
        if s.Effect == "Allow"
      ]
    ]))
    error_message = "Allow statements must list explicit actions (INF-SHARED-1)."
  }
}

run "one_env_creates_one_apply_role" {
  command = plan

  variables {
    envs = ["prod"]
  }

  assert {
    condition     = toset(keys(aws_iam_role.apply)) == toset(["prod"])
    error_message = "With envs = [prod] only the prod apply role may exist."
  }

  assert {
    condition     = !anytrue([for k, p in aws_iam_policy.ci : startswith(k, "graveyard-dev-")])
    error_message = "With envs = [prod] no dev policy may exist."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-guard"].policy).Statement : s
      if s.Sid == "DenyOtherEnv"
    ][0].Resource == ["arn:aws:*:*:*:*graveyard-dev-*", "arn:aws:*:*:*:*graveyard/dev/*"]
    error_message = "The prod role must still deny the dev env when dev is not managed here."
  }
}

run "the_apply_outputs_are_the_roles" {
  command = plan

  assert {
    condition     = toset(keys(output.apply_role_arns)) == toset(["dev", "prod"])
    error_message = "apply_role_arns must be keyed by env."
  }
}
