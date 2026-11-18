# Workload boundaries (INF-APPLY-7, INF-SHARED-1..4, INF-SHARED-6, INF-REG-2, decisions F5 and E1..E5).
# Offline; real policy JSON.

mock_provider "aws" {}

variables {
  account_id        = "123456789012"
  partition         = "aws"
  repo_owner        = "olajaido"
  repo_name         = "graveyard"
  state_bucket_name = "graveyard-tfstate-abcd1234"
  state_kms_key_arn = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
}

run "there_is_one_boundary_per_env_on_the_ci_path" {
  command = plan

  assert {
    condition     = toset(keys({ for k2, p2 in aws_iam_policy.ci : k2 => p2 if endswith(k2, "-boundary") })) == toset(["graveyard-dev-boundary", "graveyard-prod-boundary"])
    error_message = "There must be one boundary per env."
  }

  assert {
    condition     = alltrue([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if endswith(k2, "-boundary") } : p.path == "/graveyard-ci/" && p.name == k && length(p.policy) <= 6144])
    error_message = "Boundaries sit on the CI path, are named by their key and stay under 6,144 characters."
  }

  assert {
    condition     = output.boundary_arns == { dev = "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary", prod = "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-prod-boundary" }
    error_message = "The boundary ARNs must be built from names."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] :
      [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-iam"].policy).Statement : s if s.Sid == "CreateWorkloadRoles"][0].Condition.StringEquals["iam:PermissionsBoundary"] == output.boundary_arns[e]
    ])
    error_message = "The boundary an apply role requires must be the boundary this module creates."
  }
}

run "a_boundary_never_allows_iam_billing_or_cost_explorer_and_denies_them" {
  command = plan

  assert {
    condition = !anytrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if endswith(k2, "-boundary") } : [
        for s in jsondecode(p.policy).Statement : [for a in flatten([try(s.Action, [])]) : contains(["iam", "budgets", "ce"], split(":", a)[0])]
        if s.Effect == "Allow"
      ]
    ]))
    error_message = "A boundary must not allow IAM, Budgets or Cost Explorer."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : (
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "DenyIam"][0] == { Sid = "DenyIam", Effect = "Deny", Action = ["iam:*"], Resource = "*" } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "DenyCost"][0] == { Sid = "DenyCost", Effect = "Deny", Action = ["budgets:*", "ce:*"], Resource = "*" }
      )
    ])
    error_message = "A boundary must deny iam:*, budgets:* and ce:*."
  }
}

run "the_region_deny_is_in_both_boundaries" {
  command = plan

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : (
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "DenyOutsideRegion"][0] == {
          Sid       = "DenyOutsideRegion"
          Effect    = "Deny"
          NotAction = ["iam:*", "sts:*", "cloudfront:*", "wafv2:*", "acm:*", "budgets:*", "ce:*", "s3:ListAllMyBuckets", "s3:GetBucketLocation"]
          Resource  = "*"
          Condition = { StringNotEquals = { "aws:RequestedRegion" = "eu-west-2" } }
        } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "DenyGlobalOutsideUsEast1"][0] == {
          Sid       = "DenyGlobalOutsideUsEast1"
          Effect    = "Deny"
          Action    = ["cloudfront:*", "wafv2:*", "acm:*"]
          Resource  = "*"
          Condition = { StringNotEquals = { "aws:RequestedRegion" = ["eu-west-2", "us-east-1"] } }
        }
      )
    ])
    error_message = "Both region denies must be in both boundaries."
  }
}

run "a_boundary_names_only_its_own_env" {
  command = plan

  assert {
    condition = !anytrue(flatten([
      for s in jsondecode(aws_iam_policy.ci["graveyard-dev-boundary"].policy).Statement : [for r in flatten([try(s.Resource, [])]) : strcontains(r, "prod")]
      if s.Effect == "Allow"
    ]))
    error_message = "The dev boundary must not allow anything named for prod."
  }

  assert {
    condition = !anytrue(flatten([
      for s in jsondecode(aws_iam_policy.ci["graveyard-prod-boundary"].policy).Statement : [for r in flatten([try(s.Resource, [])]) : strcontains(r, "dev")]
      if s.Effect == "Allow"
    ]))
    error_message = "The prod boundary must not allow anything named for dev."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-boundary"].policy).Statement : s if s.Sid == "DynamoDbItems"][0].Resource == ["arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-*"] &&
      [for s in jsondecode(aws_iam_policy.ci["graveyard-prod-boundary"].policy).Statement : s if s.Sid == "SsmRead"][0].Resource == ["arn:aws:ssm:eu-west-2:123456789012:parameter/graveyard/prod/*", "arn:aws:ssm:eu-west-2:123456789012:parameter/graveyard/prod"] &&
      [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-boundary"].policy).Statement : s if s.Sid == "SecretValues"][0].Resource == ["arn:aws:secretsmanager:eu-west-2:123456789012:secret:graveyard/dev/*"] &&
      [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-boundary"].policy).Statement : s if s.Sid == "KmsUse"][0].Condition == { StringEquals = { "aws:ResourceTag/Env" = "dev", "aws:ResourceTag/Project" = "graveyard" } }
    )
    error_message = "Data access must be limited to the env's own names, paths and tags."
  }
}

run "the_x_ray_and_metric_exceptions_are_exactly_the_approved_ones" {
  command = plan

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : (
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "ExceptionE1"][0] == { Sid = "ExceptionE1", Effect = "Allow", Action = ["xray:PutTraceSegments"], Resource = "*" } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "ExceptionE2"][0] == { Sid = "ExceptionE2", Effect = "Allow", Action = ["xray:PutTelemetryRecords"], Resource = "*" } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "ExceptionE3"][0] == {
          Sid       = "ExceptionE3"
          Effect    = "Allow"
          Action    = ["cloudwatch:PutMetricData"]
          Resource  = "*"
          Condition = { StringEquals = { "cloudwatch:namespace" = "Graveyard/${e}" } }
        }
      )
    ])
    error_message = "E1, E2 and E3 must be exactly the approved statements."
  }

  assert {
    condition = toset(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if endswith(k2, "-boundary") } : [
        for s in jsondecode(p.policy).Statement : "${k}/${s.Sid}"
        if s.Effect == "Allow" && contains(flatten([try(s.Resource, [])]), "*")
      ]
    ])) == toset(["graveyard-dev-boundary/ExceptionE1", "graveyard-dev-boundary/ExceptionE2", "graveyard-dev-boundary/ExceptionE3", "graveyard-prod-boundary/ExceptionE1", "graveyard-prod-boundary/ExceptionE2", "graveyard-prod-boundary/ExceptionE3"])
    error_message = "Only E1, E2 and E3 may allow * as a resource in a boundary."
  }
}

run "bedrock_is_limited_to_the_exact_profiles_and_foundation_models" {
  command = plan

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : (
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "ExceptionE5Profiles"][0] == {
          Sid    = "ExceptionE5Profiles"
          Effect = "Allow"
          Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
          Resource = [
            "arn:aws:bedrock:eu-west-2:123456789012:inference-profile/eu.anthropic.claude-haiku-5-5",
            "arn:aws:bedrock:eu-west-2:123456789012:inference-profile/eu.anthropic.claude-sonnet-5-5",
          ]
        } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "ExceptionE5ModelNarrate"][0] == {
          Sid       = "ExceptionE5ModelNarrate"
          Effect    = "Allow"
          Action    = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
          Resource  = ["arn:aws:bedrock:eu-central-1::foundation-model/anthropic.claude-haiku-5-5", "arn:aws:bedrock:eu-north-1::foundation-model/anthropic.claude-haiku-5-5", "arn:aws:bedrock:eu-south-1::foundation-model/anthropic.claude-haiku-5-5", "arn:aws:bedrock:eu-south-2::foundation-model/anthropic.claude-haiku-5-5", "arn:aws:bedrock:eu-west-1::foundation-model/anthropic.claude-haiku-5-5", "arn:aws:bedrock:eu-west-2::foundation-model/anthropic.claude-haiku-5-5", "arn:aws:bedrock:eu-west-3::foundation-model/anthropic.claude-haiku-5-5"]
          Condition = { StringEquals = { "bedrock:InferenceProfileArn" = "arn:aws:bedrock:eu-west-2:123456789012:inference-profile/eu.anthropic.claude-haiku-5-5" } }
        } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s if s.Sid == "ExceptionE5ModelRites"][0] == {
          Sid       = "ExceptionE5ModelRites"
          Effect    = "Allow"
          Action    = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
          Resource  = ["arn:aws:bedrock:eu-central-1::foundation-model/anthropic.claude-sonnet-5-5", "arn:aws:bedrock:eu-north-1::foundation-model/anthropic.claude-sonnet-5-5", "arn:aws:bedrock:eu-south-1::foundation-model/anthropic.claude-sonnet-5-5", "arn:aws:bedrock:eu-south-2::foundation-model/anthropic.claude-sonnet-5-5", "arn:aws:bedrock:eu-west-1::foundation-model/anthropic.claude-sonnet-5-5", "arn:aws:bedrock:eu-west-2::foundation-model/anthropic.claude-sonnet-5-5", "arn:aws:bedrock:eu-west-3::foundation-model/anthropic.claude-sonnet-5-5"]
          Condition = { StringEquals = { "bedrock:InferenceProfileArn" = "arn:aws:bedrock:eu-west-2:123456789012:inference-profile/eu.anthropic.claude-sonnet-5-5" } }
        }
      )
    ])
    error_message = "E5 must name the exact PRD section 10.2 profiles and foundation models (INF-SHARED-6)."
  }

  assert {
    condition = !anytrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if endswith(k2, "-boundary") } : [
        for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, [])]) : strcontains(r, "eu-*") || strcontains(r, "foundation-model/*") || strcontains(r, "inference-profile/*") || strcontains(r, "inference-profile/eu.*")]
        if startswith(s.Sid, "ExceptionE5")
      ]
    ]))
    error_message = "E5 must not use eu-* or any wildcard resource."
  }

  assert {
    condition = !anytrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, [])]) : strcontains(r, "global.")]]
    ]))
    error_message = "A global. profile must never appear."
  }
}

run "bedrock_ids_and_regions_come_from_the_variables" {
  command = plan

  variables {
    bedrock_narrate_profile_id       = "eu.example.narrate-1"
    bedrock_rites_profile_id         = "eu.example.rites-2"
    bedrock_foundation_model_regions = ["eu-west-2", "eu-west-1"]
  }

  assert {
    condition     = [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-boundary"].policy).Statement : s if s.Sid == "ExceptionE5Profiles"][0].Resource == ["arn:aws:bedrock:eu-west-2:123456789012:inference-profile/eu.example.narrate-1", "arn:aws:bedrock:eu-west-2:123456789012:inference-profile/eu.example.rites-2"]
    error_message = "The profile ARNs must follow the variables."
  }

  assert {
    condition     = [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-boundary"].policy).Statement : s if s.Sid == "ExceptionE5ModelNarrate"][0].Resource == ["arn:aws:bedrock:eu-west-2::foundation-model/example.narrate-1", "arn:aws:bedrock:eu-west-1::foundation-model/example.narrate-1"]
    error_message = "The foundation-model ARNs must follow the variables and cover each configured region, in order."
  }
}

run "a_global_profile_is_rejected" {
  command = plan

  variables {
    bedrock_narrate_profile_id = "global.anthropic.claude-haiku-5-5"
  }

  expect_failures = [var.bedrock_narrate_profile_id]
}

run "a_wildcard_profile_is_rejected" {
  command = plan

  variables {
    bedrock_rites_profile_id = "eu.anthropic.*"
  }

  expect_failures = [var.bedrock_rites_profile_id]
}

run "a_wildcard_or_non_eu_region_is_rejected" {
  command = plan

  variables {
    bedrock_foundation_model_regions = ["eu-*"]
  }

  expect_failures = [var.bedrock_foundation_model_regions]
}

run "a_us_region_is_rejected" {
  command = plan

  variables {
    bedrock_foundation_model_regions = ["us-east-1"]
  }

  expect_failures = [var.bedrock_foundation_model_regions]
}
