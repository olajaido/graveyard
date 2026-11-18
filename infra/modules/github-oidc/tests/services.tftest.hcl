# Service policies of the CI roles (INF-APPLY-2, INF-APPLY-3, INF-PLAN-1, INF-SHARED-1..4, decisions SA4, F4, F5).
# Offline; real policy JSON. A read is an action whose name starts with Get, List or Describe (any case,
# so apigateway:GET counts); every other action is a write (design 5.2.7).

mock_provider "aws" {}

variables {
  account_id        = "123456789012"
  partition         = "aws"
  repo_owner        = "olajaido"
  repo_name         = "graveyard"
  state_bucket_name = "graveyard-tfstate-abcd1234"
  state_kms_key_arn = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
}

run "every_role_has_its_policies_and_stays_under_the_limits" {
  command = plan

  assert {
    condition = toset([for k, p in aws_iam_policy.ci : k if startswith(k, "graveyard-plan-")]) == toset([
      "graveyard-plan-state", "graveyard-plan-read-iam", "graveyard-plan-read-compute", "graveyard-plan-read-data",
      "graveyard-plan-read-edge", "graveyard-plan-read-ops", "graveyard-plan-guard",
    ])
    error_message = "Unexpected plan policies."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : toset([for k, p in aws_iam_policy.ci : k if startswith(k, "graveyard-${e}-apply-")]) == toset([
        for n in ["state", "iam", "compute", "data", "edge", "ops", "guard"] : "graveyard-${e}-apply-${n}"
      ])
    ])
    error_message = "Unexpected apply policies."
  }

  assert {
    condition     = alltrue([for k, p in aws_iam_policy.ci : length(p.policy) <= 6144])
    error_message = "A managed policy must be at most 6,144 characters."
  }

  assert {
    condition = (
      length(keys(aws_iam_role_policy_attachment.plan)) <= 10 &&
      length([for k, a in aws_iam_role_policy_attachment.apply : k if startswith(k, "dev/")]) <= 10 &&
      length([for k, a in aws_iam_role_policy_attachment.apply : k if startswith(k, "prod/")]) <= 10
    )
    error_message = "A role can have at most 10 managed policies."
  }

  assert {
    condition     = alltrue([for k, p in aws_iam_policy.ci : length([for s in jsondecode(p.policy).Statement : s.Sid]) == length(distinct([for s in jsondecode(p.policy).Statement : s.Sid]))])
    error_message = "Statement IDs must be unique within a policy."
  }
}

run "the_star_resource_allow_list_is_exactly_this_and_only_reads_tagged_creates_and_exceptions" {
  command = plan

  assert {
    condition = toset([for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*")]) == toset([
      "graveyard-plan-read-compute/ReadStar",
      "graveyard-plan-read-data/ReadStar",
      "graveyard-plan-read-edge/ReadStar",
      "graveyard-plan-read-ops/ReadStar",
      "graveyard-dev-apply-compute/ReadStar",
      "graveyard-dev-apply-compute/ExceptionE4",
      "graveyard-dev-apply-data/KmsCreateKey",
      "graveyard-dev-apply-data/ReadStar",
      "graveyard-dev-apply-edge/CreateDistributions",
      "graveyard-dev-apply-edge/CreateCloudFrontFunctions",
      "graveyard-dev-apply-edge/ExceptionE6",
      "graveyard-dev-apply-edge/AcmRequest",
      "graveyard-dev-apply-edge/ReadStar",
      "graveyard-dev-apply-ops/CreateGuardrails",
      "graveyard-dev-apply-ops/ReadStar",
      "graveyard-prod-apply-compute/ReadStar",
      "graveyard-prod-apply-compute/ExceptionE4",
      "graveyard-prod-apply-data/KmsCreateKey",
      "graveyard-prod-apply-data/ReadStar",
      "graveyard-prod-apply-edge/CreateDistributions",
      "graveyard-prod-apply-edge/CreateCloudFrontFunctions",
      "graveyard-prod-apply-edge/ExceptionE6",
      "graveyard-prod-apply-edge/AcmRequest",
      "graveyard-prod-apply-edge/ReadStar",
      "graveyard-prod-apply-ops/CreateGuardrails",
      "graveyard-prod-apply-ops/ReadStar",
    ])
    error_message = "The statements that allow * as a resource must be exactly the approved list (INF-SHARED-2)."
  }

  assert {
    condition = alltrue([
      for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : (
        !contains(flatten([try(x.stmt.Resource, [])]), "*") ||
        startswith(x.stmt.Sid, "Exception") ||
        (
          x.stmt.Sid != "ReadStar" ? (
            x.stmt.Condition.StringEquals["aws:RequestTag/Project"] == "graveyard" &&
            alltrue([for a in flatten([try(x.stmt.Action, [])]) : contains(["kms:CreateKey", "cloudfront:CreateDistribution", "cloudfront:CreateFunction", "acm:RequestCertificate", "bedrock:CreateGuardrail"], a)])
            ) : (
            alltrue([for a in flatten([try(x.stmt.Action, [])]) : can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))])
          )
        )
      )
    ])
    error_message = "A statement on * must be a read, a create with the Project RequestTag condition, or an approved exception."
  }

  assert {
    condition = alltrue([
      for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : alltrue([for a in flatten([try(x.stmt.Action, [])]) : contains(["xray:GetSamplingRules", "kms:ListAliases", "ssm:DescribeParameters", "cloudfront:ListDistributions", "cloudfront:ListFunctions", "cloudfront:ListCachePolicies", "cloudfront:GetCachePolicy", "cloudfront:ListResponseHeadersPolicies", "cloudfront:GetResponseHeadersPolicy", "cloudfront:ListOriginAccessControls", "cloudfront:GetOriginAccessControl", "wafv2:ListWebACLs", "wafv2:ListIPSets", "wafv2:ListRuleGroups", "wafv2:ListAvailableManagedRuleGroups", "wafv2:DescribeManagedRuleGroup", "acm:ListCertificates", "logs:DescribeLogGroups", "cloudwatch:DescribeAlarms", "synthetics:DescribeCanaries", "bedrock:ListGuardrails", "bedrock:ListFoundationModels", "bedrock:ListInferenceProfiles"], a)])
      if x.stmt.Sid == "ReadStar"
    ])
    error_message = "ReadStar statements may hold only the named metadata reads and list calls."
  }

  assert {
    condition = toset(flatten([
      for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : flatten([try(x.stmt.Action, [])])
      if startswith(x.stmt.Sid, "Exception")
    ])) == toset(["ecr:GetAuthorizationToken", "cloudfront:CreateOriginAccessControl", "cloudfront:GetOriginAccessControl", "cloudfront:ListOriginAccessControls", "cloudfront:UpdateOriginAccessControl", "cloudfront:DeleteOriginAccessControl"])
    error_message = "The exception statements in the CI roles must be exactly E4 and E6."
  }

  assert {
    condition = (
      [for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : x.stmt if x.policy == "graveyard-dev-apply-compute" && x.stmt.Sid == "ExceptionE4"][0].Action == ["ecr:GetAuthorizationToken"] &&
      [for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : x.stmt if x.policy == "graveyard-prod-apply-edge" && x.stmt.Sid == "ExceptionE6"][0].Action == ["cloudfront:CreateOriginAccessControl", "cloudfront:GetOriginAccessControl", "cloudfront:ListOriginAccessControls", "cloudfront:UpdateOriginAccessControl", "cloudfront:DeleteOriginAccessControl"]
    )
    error_message = "E4 and E6 must list exactly the approved actions."
  }
}

run "tagged_creates_need_both_the_project_and_the_env_tag" {
  command = plan

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : alltrue([
        for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : x.stmt.Condition == { StringEquals = { "aws:RequestTag/Env" = e, "aws:RequestTag/Project" = "graveyard" } }
        if startswith(x.policy, "graveyard-${e}-apply-") && contains(flatten([try(x.stmt.Resource, [])]), "*") && !startswith(x.stmt.Sid, "Exception") && x.stmt.Sid != "ReadStar"
      ])
    ])
    error_message = "Every create on * must require RequestTag Project=graveyard and RequestTag Env=<env>."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : alltrue([
        for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : x.stmt.Condition == { StringEquals = { "aws:ResourceTag/Env" = e, "aws:ResourceTag/Project" = "graveyard" } }
        if startswith(x.policy, "graveyard-${e}-apply-") && contains(["KmsManageKeys", "ManageHttpApis", "ManageDistributions", "AcmManage", "ManageGuardrails"], x.stmt.Sid)
      ])
    ])
    error_message = "Every change to a generated-ID resource must require ResourceTag Project=graveyard and ResourceTag Env=<env>."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : alltrue([
        for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : x.stmt.Condition == { StringEquals = { "aws:RequestTag/Env" = e, "aws:RequestTag/Project" = "graveyard" } }
        if startswith(x.policy, "graveyard-${e}-apply-") && contains(["KmsTagNewKey", "TagHttpApis", "TagNewDistributions", "AcmTagNew", "TagNewGuardrails"], x.stmt.Sid)
      ])
    ])
    error_message = "Create-time tagging must require the Project and Env request tags."
  }

  assert {
    condition = (
      [for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : x.stmt if x.policy == "graveyard-dev-apply-data" && x.stmt.Sid == "KmsCreateKey"][0] == {
        Sid       = "KmsCreateKey"
        Effect    = "Allow"
        Action    = ["kms:CreateKey"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestTag/Env" = "dev", "aws:RequestTag/Project" = "graveyard" } }
      }
    )
    error_message = "kms:CreateKey must be on * with exactly the two request tags."
  }
}

run "every_write_is_limited_to_a_graveyard_name_a_graveyard_path_or_the_project_tag" {
  command = plan

  assert {
    condition = alltrue([
      for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : (
        !anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]) ||
        startswith(x.stmt.Sid, "Exception") ||
        alltrue([for r in flatten([try(x.stmt.Resource, [])]) : can(regex("graveyard[-/]", r))]) ||
        try(x.stmt.Condition.StringEquals["aws:ResourceTag/Project"], "") == "graveyard" ||
        try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") == "graveyard"
      )
    ])
    error_message = "A write must name graveyard-* or graveyard/ resources, or carry the Project tag condition (INF-SHARED-1)."
  }

  assert {
    condition = alltrue([
      for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : !contains(flatten([try(x.stmt.Resource, [])]), "*") || !anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]) || x.stmt.Condition.StringEquals != null || startswith(x.stmt.Sid, "Exception")
    ])
    error_message = "A write on * must carry a condition or be an approved exception."
  }

  assert {
    condition = !anytrue(flatten([
      for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for a in flatten([try(x.stmt.Action, [])]) : contains(["iam:CreateServiceLinkedRole", "iam:UpdateAccountPasswordPolicy", "iam:CreateAccountAlias", "s3:PutAccountPublicAccessBlock", "logs:PutResourcePolicy", "logs:CreateLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "cloudfront:CreateCachePolicy", "cloudfront:CreateResponseHeadersPolicy", "lambda:ListFunctions", "lambda:CreateEventSourceMapping"], a) || startswith(a, "organizations:") || startswith(a, "account:")]
    ]))
    error_message = "No action of INF-SHARED-3 may be allowed."
  }

  assert {
    condition     = !anytrue(flatten([for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for a in flatten([try(x.stmt.Action, [])]) : strcontains(a, "*")]]))
    error_message = "Allow statements must list explicit actions."
  }
}

run "only_the_services_of_the_architecture_are_used" {
  command = plan

  assert {
    condition = alltrue(flatten([
      for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for a in flatten([try(x.stmt.Action, [])]) : contains(["s3", "cloudfront", "wafv2", "acm", "apigateway", "lambda", "ecr", "states", "dynamodb", "bedrock", "secretsmanager", "ssm", "kms", "iam", "logs", "cloudwatch", "synthetics", "sns", "xray", "scheduler"], split(":", a)[0])]
    ]))
    error_message = "An action is outside the services of INF-APPLY-2."
  }
}

run "the_plan_read_policies_read_configuration_and_never_data" {
  command = plan

  assert {
    condition = alltrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-read-") } : [
        for s in jsondecode(p.policy).Statement : [for a in flatten([s.Action]) : can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]
      ]
    ]))
    error_message = "A plan read policy may contain only Get, List and Describe actions (INF-PLAN-1)."
  }

  assert {
    condition = !anytrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-read-") } : [
        for s in jsondecode(p.policy).Statement : [
          for a in flatten([s.Action]) : startswith(a, "s3:GetObject") || contains(["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:Scan", "secretsmanager:GetSecretValue", "kms:Decrypt"], a)
        ]
      ]
    ]))
    error_message = "A plan read policy must not read objects, table items or secret values."
  }

  assert {
    condition = alltrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-read-") } : [
        for s in jsondecode(p.policy).Statement : [for r in flatten([s.Resource]) : r == "*" ? s.Sid == "ReadStar" : true]
      ]
    ]))
    error_message = "Only the ReadStar statements of a plan read policy may use * as a resource."
  }

  assert {
    condition = alltrue([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-read-") } : alltrue([
        for s in jsondecode(p.policy).Statement : s.Effect == "Allow"
      ])
    ])
    error_message = "Plan read policies contain only Allow statements."
  }
}

run "the_plan_read_policies_cover_both_envs_and_the_tag_conditions_name_both" {
  command = plan

  assert {
    condition = (
      [for s in jsondecode(aws_iam_policy.ci["graveyard-plan-read-compute"].policy).Statement : s if s.Sid == "Lambda"][0].Resource == [
        "arn:aws:lambda:eu-west-2:123456789012:function:graveyard-dev-*",
        "arn:aws:lambda:eu-west-2:123456789012:function:graveyard-prod-*",
      ]
    )
    error_message = "Plan reads must cover the dev and prod Lambda functions."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_iam_policy.ci["graveyard-plan-read-data"].policy).Statement : s if s.Sid == "KmsKeys"][0].Condition == {
        StringEquals = { "aws:ResourceTag/Env" = ["dev", "prod"], "aws:ResourceTag/Project" = "graveyard" }
      }
    )
    error_message = "Plan key reads must require the Project tag and an Env of dev or prod."
  }
}

run "the_apply_policies_hold_the_expected_boundaries_between_services_and_envs" {
  command = plan

  assert {
    condition = (
      [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-compute"].policy).Statement : s if s.Sid == "Lambda"][0].Resource == ["arn:aws:lambda:eu-west-2:123456789012:function:graveyard-dev-*"] &&
      contains([for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-compute"].policy).Statement : s if s.Sid == "Lambda"][0].Action, "lambda:PutFunctionConcurrency")
    )
    error_message = "The dev role must set reserved concurrency on dev functions only (SA5)."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-data"].policy).Statement : s if s.Sid == "Ssm"][0].Resource == ["arn:aws:ssm:eu-west-2:123456789012:parameter/graveyard/prod/*"] &&
      [for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-data"].policy).Statement : s if s.Sid == "SecretContainers"][0].Resource == ["arn:aws:secretsmanager:eu-west-2:123456789012:secret:graveyard/prod/*"]
    )
    error_message = "SSM and Secrets Manager must use the /graveyard/<env>/ paths of security.md."
  }

  assert {
    condition = !anytrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if strcontains(k2, "-apply-") } : [
        for s in jsondecode(p.policy).Statement : [for a in flatten([try(s.Action, [])]) : contains(["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"], a)]
        if s.Effect == "Allow"
      ]
    ]))
    error_message = "Secret values must never be readable or writable by an apply role."
  }

  assert {
    condition = (
      toset([for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-edge"].policy).Statement : s.Sid if contains(flatten([try(s.Resource, [])]), "*") && s.Sid != "ReadStar"]) ==
      toset(["CreateDistributions", "CreateCloudFrontFunctions", "ExceptionE6", "AcmRequest"])
    )
    error_message = "The edge policy may have exactly these statements on *, besides ReadStar."
  }

  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : (
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-edge"].policy).Statement : s if s.Sid == "Waf"][0].Resource == [
          "arn:aws:wafv2:eu-west-2:123456789012:regional/webacl/graveyard-${e}-*/*",
          "arn:aws:wafv2:eu-west-2:123456789012:regional/ipset/graveyard-${e}-*/*",
          "arn:aws:wafv2:eu-west-2:123456789012:regional/rulegroup/graveyard-${e}-*/*",
          "arn:aws:wafv2:us-east-1:123456789012:global/webacl/graveyard-${e}-*/*",
          "arn:aws:wafv2:us-east-1:123456789012:global/ipset/graveyard-${e}-*/*",
          "arn:aws:wafv2:us-east-1:123456789012:global/rulegroup/graveyard-${e}-*/*",
        ]
      )
    ])
    error_message = "WAF must cover the env's regional and CloudFront-scope resources by name."
  }
}

run "removed_actions_stay_removed_in_a_single_env_run" {
  command = plan

  variables {
    envs = ["prod"]
  }

  assert {
    condition = !anytrue(flatten([
      for x in flatten([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if !endswith(k2, "-boundary") } : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for a in flatten([try(x.stmt.Action, [])]) : contains(["iam:CreateServiceLinkedRole", "iam:UpdateAccountPasswordPolicy", "iam:CreateAccountAlias", "s3:PutAccountPublicAccessBlock", "logs:PutResourcePolicy", "logs:CreateLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "cloudfront:CreateCachePolicy", "cloudfront:CreateResponseHeadersPolicy", "lambda:ListFunctions", "lambda:CreateEventSourceMapping"], a)]
    ]))
    error_message = "The removed actions must stay removed."
  }

  assert {
    condition     = toset([for k, p in aws_iam_policy.ci : k if startswith(k, "graveyard-dev-")]) == toset([])
    error_message = "A prod-only run must have no dev policy."
  }
}
