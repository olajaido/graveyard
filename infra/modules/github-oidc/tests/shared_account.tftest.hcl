# Shared-account blast radius (INF-SHARED-1..5, decision SA4, flags F4 and F5). Offline; real policy JSON.
# The first runs check the real policies of every CI role and both boundaries. The bad-sample runs apply the
# same rule expressions to the real policies with ONE policy replaced by a bad one, and show the rules catching
# it, so the rules cannot pass vacuously.
#
# A read is an action whose name starts with Get, List or Describe (any case, so apigateway:GET counts).
# Every other action is a write.

mock_provider "aws" {}

variables {
  account_id        = "123456789012"
  partition         = "aws"
  repo_owner        = "olajaido"
  repo_name         = "graveyard"
  repo_owner_id     = "102736714"
  repo_id           = "1443508961"
  state_bucket_name = "graveyard-tfstate-abcd1234"
  state_kms_key_arn = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
}

run "every_write_names_a_graveyard_resource_or_carries_the_project_tag" {
  command = plan

  assert {
    condition     = [for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]) && !startswith(x.stmt.Sid, "Exception") && !alltrue([for r in flatten([try(x.stmt.Resource, [])]) : can(regex("graveyard[-/]", r))]) && try(x.stmt.Condition.StringEquals["aws:ResourceTag/Project"], "") != "graveyard" && try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") != "graveyard"] == []
    error_message = "A write Allow statement names no graveyard-* or graveyard/ resource and has no Project tag condition (INF-SHARED-1)."
  }

  assert {
    condition     = length(flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]])) > 100
    error_message = "The rule must be looking at the real statements: expected well over 100 Allow statements across the CI policies and boundaries."
  }
}

run "the_star_resource_allow_list_is_exactly_this_and_holds_only_reads_tagged_creates_and_exceptions" {
  command = plan

  assert {
    condition     = [for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*") && !startswith(x.stmt.Sid, "Exception") && !(alltrue([for a in flatten([try(x.stmt.Action, [])]) : contains(["xray:GetSamplingRules", "kms:ListAliases", "ssm:DescribeParameters", "cloudfront:ListDistributions", "cloudfront:ListFunctions", "cloudfront:ListCachePolicies", "cloudfront:GetCachePolicy", "cloudfront:ListResponseHeadersPolicies", "cloudfront:GetResponseHeadersPolicy", "cloudfront:ListOriginAccessControls", "cloudfront:GetOriginAccessControl", "wafv2:ListWebACLs", "wafv2:ListIPSets", "wafv2:ListRuleGroups", "wafv2:ListAvailableManagedRuleGroups", "wafv2:DescribeManagedRuleGroup", "acm:ListCertificates", "logs:DescribeLogGroups", "cloudwatch:DescribeAlarms", "synthetics:DescribeCanaries", "bedrock:ListGuardrails", "bedrock:ListFoundationModels", "bedrock:ListInferenceProfiles"], a)]) || (try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") == "graveyard" && alltrue([for a in flatten([try(x.stmt.Action, [])]) : contains(["kms:CreateKey", "cloudfront:CreateDistribution", "cloudfront:CreateFunction", "acm:RequestCertificate", "bedrock:CreateGuardrail"], a)])))] == []
    error_message = "A statement on * is neither a named read, a RequestTag create, nor an approved exception (INF-SHARED-2)."
  }

  assert {
    condition = toset([for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*")]) == toset([
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
      "graveyard-dev-apply-ops/ExceptionE7",
      "graveyard-dev-apply-edge/AcmRequest",
      "graveyard-dev-apply-edge/ReadStar",
      "graveyard-dev-apply-ops/CreateGuardrails",
      "graveyard-dev-apply-ops/ReadStar",
      "graveyard-dev-boundary/ExceptionE1",
      "graveyard-dev-boundary/ExceptionE2",
      "graveyard-dev-boundary/ExceptionE3",
      "graveyard-dev-boundary/ExceptionE10",
      "graveyard-prod-apply-compute/ReadStar",
      "graveyard-prod-apply-compute/ExceptionE4",
      "graveyard-prod-apply-data/KmsCreateKey",
      "graveyard-prod-apply-data/ReadStar",
      "graveyard-prod-apply-edge/CreateDistributions",
      "graveyard-prod-apply-edge/CreateCloudFrontFunctions",
      "graveyard-prod-apply-edge/ExceptionE6",
      "graveyard-dev-apply-compute/ExceptionE8",
      "graveyard-prod-apply-compute/ExceptionE8",
      "graveyard-plan-read-compute/ExceptionE8",
      "graveyard-prod-apply-ops/ExceptionE7",
      "graveyard-prod-apply-edge/AcmRequest",
      "graveyard-prod-apply-edge/ReadStar",
      "graveyard-prod-apply-ops/CreateGuardrails",
      "graveyard-prod-apply-ops/ReadStar",
      "graveyard-prod-boundary/ExceptionE1",
      "graveyard-prod-boundary/ExceptionE2",
      "graveyard-prod-boundary/ExceptionE3",
      "graveyard-prod-boundary/ExceptionE10",
    ])
    error_message = "The set of statements that allow * must be exactly the approved list."
  }

  assert {
    condition     = [for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*") && !startswith(x.stmt.Sid, "Exception") && try(x.stmt.Condition, null) == null && anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))])] == []
    error_message = "A write on * must carry a condition unless it is an approved exception."
  }
}

run "none_of_the_removed_actions_is_allowed" {
  command = plan

  assert {
    condition     = flatten([for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for a in flatten([try(x.stmt.Action, [])]) : "${x.policy}/${x.stmt.Sid}/${a}" if contains(["iam:CreateServiceLinkedRole", "iam:UpdateAccountPasswordPolicy", "iam:CreateAccountAlias", "s3:PutAccountPublicAccessBlock", "logs:PutResourcePolicy", "cloudfront:CreateCachePolicy", "cloudfront:CreateResponseHeadersPolicy", "lambda:ListFunctions", "lambda:CreateEventSourceMapping"], a) && !(a == "logs:PutResourcePolicy" && endswith(x.policy, "-boundary") && x.stmt.Sid == "ExceptionE10") || startswith(a, "organizations:") || startswith(a, "account:")]]) == []
    error_message = "An action of INF-SHARED-3 is allowed."
  }
}

run "the_exceptions_are_exactly_the_approved_ones" {
  command = plan

  assert {
    condition = toset([for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if startswith(x.stmt.Sid, "Exception")]) == toset([
      "graveyard-dev-apply-compute/ExceptionE4",
      "graveyard-dev-apply-edge/ExceptionE6",
      "graveyard-dev-apply-ops/ExceptionE7",
      "graveyard-dev-boundary/ExceptionE1",
      "graveyard-dev-boundary/ExceptionE2",
      "graveyard-dev-boundary/ExceptionE3",
      "graveyard-dev-boundary/ExceptionE10",
      "graveyard-dev-boundary/ExceptionE5Profiles",
      "graveyard-dev-boundary/ExceptionE5ModelNarrate",
      "graveyard-dev-boundary/ExceptionE5ModelRites",
      "graveyard-prod-apply-compute/ExceptionE4",
      "graveyard-prod-apply-edge/ExceptionE6",
      "graveyard-dev-apply-compute/ExceptionE8",
      "graveyard-prod-apply-compute/ExceptionE8",
      "graveyard-plan-read-compute/ExceptionE8",
      "graveyard-dev-apply-edge/ExceptionE9",
      "graveyard-prod-apply-edge/ExceptionE9",
      "graveyard-prod-apply-ops/ExceptionE7",
      "graveyard-prod-boundary/ExceptionE1",
      "graveyard-prod-boundary/ExceptionE2",
      "graveyard-prod-boundary/ExceptionE3",
      "graveyard-prod-boundary/ExceptionE10",
      "graveyard-prod-boundary/ExceptionE5Profiles",
      "graveyard-prod-boundary/ExceptionE5ModelNarrate",
      "graveyard-prod-boundary/ExceptionE5ModelRites",
    ])
    error_message = "The exception statements must be exactly E1 to E10 as approved: E1 to E10 (INF-SHARED-4)."
  }

  assert {
    condition     = toset(flatten([for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : flatten([try(x.stmt.Action, [])]) if startswith(x.stmt.Sid, "Exception")])) == toset(["xray:PutTraceSegments", "xray:PutTelemetryRecords", "cloudwatch:PutMetricData", "ecr:GetAuthorizationToken", "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "cloudfront:CreateOriginAccessControl", "cloudfront:GetOriginAccessControl", "cloudfront:ListOriginAccessControls", "cloudfront:UpdateOriginAccessControl", "cloudfront:DeleteOriginAccessControl", "states:ValidateStateMachineDefinition", "apigateway:POST", "apigateway:GET", "apigateway:DELETE", "logs:PutResourcePolicy", "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"])
    error_message = "The exception statements may contain only the approved actions."
  }

  assert {
    condition     = flatten([for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for r in flatten([try(x.stmt.Resource, [])]) : "${x.policy}/${x.stmt.Sid}/${r}" if strcontains(r, "*")] if startswith(x.stmt.Sid, "ExceptionE5")]) == []
    error_message = "E5 must not use a wildcard resource such as eu-* or foundation-model/* (INF-SHARED-6)."
  }
}

run "bad_sample_an_unscoped_s3_write_on_star" {
  command = plan

  # A write with no name, path or tag limit, on *.

  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["s3:PutObject"], Resource = "*" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]) && !startswith(x.stmt.Sid, "Exception") && !alltrue([for r in flatten([try(x.stmt.Resource, [])]) : can(regex("graveyard[-/]", r))]) && try(x.stmt.Condition.StringEquals["aws:ResourceTag/Project"], "") != "graveyard" && try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") != "graveyard"], "graveyard-dev-apply-data/Bad")
    error_message = "The write rule must catch an unscoped s3:PutObject."
  }

  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["s3:PutObject"], Resource = "*" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*") && !startswith(x.stmt.Sid, "Exception") && !(alltrue([for a in flatten([try(x.stmt.Action, [])]) : contains(["xray:GetSamplingRules", "kms:ListAliases", "ssm:DescribeParameters", "cloudfront:ListDistributions", "cloudfront:ListFunctions", "cloudfront:ListCachePolicies", "cloudfront:GetCachePolicy", "cloudfront:ListResponseHeadersPolicies", "cloudfront:GetResponseHeadersPolicy", "cloudfront:ListOriginAccessControls", "cloudfront:GetOriginAccessControl", "wafv2:ListWebACLs", "wafv2:ListIPSets", "wafv2:ListRuleGroups", "wafv2:ListAvailableManagedRuleGroups", "wafv2:DescribeManagedRuleGroup", "acm:ListCertificates", "logs:DescribeLogGroups", "cloudwatch:DescribeAlarms", "synthetics:DescribeCanaries", "bedrock:ListGuardrails", "bedrock:ListFoundationModels", "bedrock:ListInferenceProfiles"], a)]) || (try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") == "graveyard" && alltrue([for a in flatten([try(x.stmt.Action, [])]) : contains(["kms:CreateKey", "cloudfront:CreateDistribution", "cloudfront:CreateFunction", "acm:RequestCertificate", "bedrock:CreateGuardrail"], a)])))], "graveyard-dev-apply-data/Bad")
    error_message = "The star rule must catch it."
  }

  assert {
    condition     = contains(toset([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["s3:PutObject"], Resource = "*" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*")]), "graveyard-dev-apply-data/Bad")
    error_message = "The allow-list must show the extra statement."
  }

  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["s3:PutObject"], Resource = "*" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*") && !startswith(x.stmt.Sid, "Exception") && try(x.stmt.Condition, null) == null && anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))])], "graveyard-dev-apply-data/Bad")
    error_message = "The unconditioned-write rule must catch it."
  }

  assert {
    condition = toset([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["s3:PutObject"], Resource = "*" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*")]) != toset([
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
      "graveyard-dev-apply-ops/ExceptionE7",
      "graveyard-dev-apply-edge/AcmRequest",
      "graveyard-dev-apply-edge/ReadStar",
      "graveyard-dev-apply-ops/CreateGuardrails",
      "graveyard-dev-apply-ops/ReadStar",
      "graveyard-dev-boundary/ExceptionE1",
      "graveyard-dev-boundary/ExceptionE2",
      "graveyard-dev-boundary/ExceptionE3",
      "graveyard-dev-boundary/ExceptionE10",
      "graveyard-prod-apply-compute/ReadStar",
      "graveyard-prod-apply-compute/ExceptionE4",
      "graveyard-prod-apply-data/KmsCreateKey",
      "graveyard-prod-apply-data/ReadStar",
      "graveyard-prod-apply-edge/CreateDistributions",
      "graveyard-prod-apply-edge/CreateCloudFrontFunctions",
      "graveyard-prod-apply-edge/ExceptionE6",
      "graveyard-dev-apply-compute/ExceptionE8",
      "graveyard-prod-apply-compute/ExceptionE8",
      "graveyard-plan-read-compute/ExceptionE8",
      "graveyard-prod-apply-ops/ExceptionE7",
      "graveyard-prod-apply-edge/AcmRequest",
      "graveyard-prod-apply-edge/ReadStar",
      "graveyard-prod-apply-ops/CreateGuardrails",
      "graveyard-prod-apply-ops/ReadStar",
      "graveyard-prod-boundary/ExceptionE1",
      "graveyard-prod-boundary/ExceptionE2",
      "graveyard-prod-boundary/ExceptionE3",
      "graveyard-prod-boundary/ExceptionE10",
    ])
    error_message = "The exact allow-list must fail when a statement is added."
  }
}

run "bad_sample_a_lambda_write_on_another_projects_functions" {
  command = plan

  # A write on a name that is not graveyard-*.

  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-compute" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["lambda:CreateFunction"], Resource = ["arn:aws:lambda:eu-west-2:123456789012:function:other-*"] }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]) && !startswith(x.stmt.Sid, "Exception") && !alltrue([for r in flatten([try(x.stmt.Resource, [])]) : can(regex("graveyard[-/]", r))]) && try(x.stmt.Condition.StringEquals["aws:ResourceTag/Project"], "") != "graveyard" && try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") != "graveyard"], "graveyard-dev-apply-compute/Bad")
    error_message = "The write rule must catch a write on another project's functions."
  }

  assert {
    condition     = !contains(toset([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-compute" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["lambda:CreateFunction"], Resource = ["arn:aws:lambda:eu-west-2:123456789012:function:other-*"] }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*")]), "graveyard-dev-apply-compute/Bad")
    error_message = "It is not on *, so it must not appear in the star list."
  }
}

run "bad_sample_a_wrong_case_project_tag" {
  command = plan

  # The tag value has the wrong case.

  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["kms:PutKeyPolicy"], Resource = ["arn:aws:kms:eu-west-2:123456789012:key/*"], Condition = { StringEquals = { "aws:ResourceTag/Project" = "Graveyard" } } }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]) && !startswith(x.stmt.Sid, "Exception") && !alltrue([for r in flatten([try(x.stmt.Resource, [])]) : can(regex("graveyard[-/]", r))]) && try(x.stmt.Condition.StringEquals["aws:ResourceTag/Project"], "") != "graveyard" && try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") != "graveyard"], "graveyard-dev-apply-data/Bad")
    error_message = "The Project tag is case-sensitive: Graveyard must not count."
  }
}

run "bad_sample_a_correct_tag_condition_passes" {
  command = plan

  # The same write with the correct tag is accepted, so the rule is not just rejecting everything.

  assert {
    condition     = !contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Good", Effect = "Allow", Action = ["kms:PutKeyPolicy"], Resource = ["arn:aws:kms:eu-west-2:123456789012:key/*"], Condition = { StringEquals = { "aws:ResourceTag/Project" = "graveyard" } } }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if anytrue([for a in flatten([try(x.stmt.Action, [])]) : !can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]) && !startswith(x.stmt.Sid, "Exception") && !alltrue([for r in flatten([try(x.stmt.Resource, [])]) : can(regex("graveyard[-/]", r))]) && try(x.stmt.Condition.StringEquals["aws:ResourceTag/Project"], "") != "graveyard" && try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") != "graveyard"], "graveyard-dev-apply-data/Good")
    error_message = "A correctly tagged write must pass the write rule."
  }
}

run "bad_sample_a_create_on_star_that_is_not_an_approved_create" {
  command = plan

  # A RequestTag create that is not on the approved list.

  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-edge" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["ec2:RunInstances"], Resource = "*", Condition = { StringEquals = { "aws:RequestTag/Project" = "graveyard" } } }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Resource, [])]), "*") && !startswith(x.stmt.Sid, "Exception") && !(alltrue([for a in flatten([try(x.stmt.Action, [])]) : contains(["xray:GetSamplingRules", "kms:ListAliases", "ssm:DescribeParameters", "cloudfront:ListDistributions", "cloudfront:ListFunctions", "cloudfront:ListCachePolicies", "cloudfront:GetCachePolicy", "cloudfront:ListResponseHeadersPolicies", "cloudfront:GetResponseHeadersPolicy", "cloudfront:ListOriginAccessControls", "cloudfront:GetOriginAccessControl", "wafv2:ListWebACLs", "wafv2:ListIPSets", "wafv2:ListRuleGroups", "wafv2:ListAvailableManagedRuleGroups", "wafv2:DescribeManagedRuleGroup", "acm:ListCertificates", "logs:DescribeLogGroups", "cloudwatch:DescribeAlarms", "synthetics:DescribeCanaries", "bedrock:ListGuardrails", "bedrock:ListFoundationModels", "bedrock:ListInferenceProfiles"], a)]) || (try(x.stmt.Condition.StringEquals["aws:RequestTag/Project"], "") == "graveyard" && alltrue([for a in flatten([try(x.stmt.Action, [])]) : contains(["kms:CreateKey", "cloudfront:CreateDistribution", "cloudfront:CreateFunction", "acm:RequestCertificate", "bedrock:CreateGuardrail"], a)])))], "graveyard-dev-apply-edge/Bad")
    error_message = "A create on * outside the approved creates must be caught even with the tag condition."
  }
}

run "bad_sample_removed_actions_with_an_otherwise_valid_scope" {
  command = plan

  # Removed actions with a valid name scope and tag.

  assert {
    condition     = length(flatten([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-prod-apply-ops" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["iam:CreateServiceLinkedRole", "logs:PutResourcePolicy"], Resource = "arn:aws:iam::123456789012:role/graveyard-prod/graveyard-prod-x", Condition = { StringEquals = { "aws:ResourceTag/Project" = "graveyard" } } }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for a in flatten([try(x.stmt.Action, [])]) : "${x.policy}/${x.stmt.Sid}/${a}" if contains(["iam:CreateServiceLinkedRole", "iam:UpdateAccountPasswordPolicy", "iam:CreateAccountAlias", "s3:PutAccountPublicAccessBlock", "logs:PutResourcePolicy", "cloudfront:CreateCachePolicy", "cloudfront:CreateResponseHeadersPolicy", "lambda:ListFunctions", "lambda:CreateEventSourceMapping"], a) && !(a == "logs:PutResourcePolicy" && endswith(x.policy, "-boundary") && x.stmt.Sid == "ExceptionE10") || startswith(a, "organizations:") || startswith(a, "account:")]])) == 2
    error_message = "Both removed actions must be caught."
  }
}

run "bad_sample_an_organizations_action" {
  command = plan

  # An account-wide service.

  assert {
    condition     = length(flatten([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-prod-apply-ops" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Allow", Action = ["organizations:DescribeOrganization"], Resource = "arn:aws:iam::123456789012:role/graveyard-prod/graveyard-prod-x" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for a in flatten([try(x.stmt.Action, [])]) : "${x.policy}/${x.stmt.Sid}/${a}" if contains(["iam:CreateServiceLinkedRole", "iam:UpdateAccountPasswordPolicy", "iam:CreateAccountAlias", "s3:PutAccountPublicAccessBlock", "logs:PutResourcePolicy", "cloudfront:CreateCachePolicy", "cloudfront:CreateResponseHeadersPolicy", "lambda:ListFunctions", "lambda:CreateEventSourceMapping"], a) && !(a == "logs:PutResourcePolicy" && endswith(x.policy, "-boundary") && x.stmt.Sid == "ExceptionE10") || startswith(a, "organizations:") || startswith(a, "account:")]])) == 1
    error_message = "organizations:* must be caught."
  }
}

run "bad_sample_an_extra_exception" {
  command = plan

  # An exception that nobody approved.

  assert {
    condition     = contains(toset([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-boundary" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "ExceptionE9", Effect = "Allow", Action = ["ec2:RunInstances"], Resource = "*" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if startswith(x.stmt.Sid, "Exception")]), "graveyard-dev-boundary/ExceptionE9")
    error_message = "The exception set must show the unapproved exception."
  }

  assert {
    condition = toset([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-boundary" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "ExceptionE9", Effect = "Allow", Action = ["ec2:RunInstances"], Resource = "*" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if startswith(x.stmt.Sid, "Exception")]) != toset([
      "graveyard-dev-apply-compute/ExceptionE4",
      "graveyard-dev-apply-edge/ExceptionE6",
      "graveyard-dev-apply-ops/ExceptionE7",
      "graveyard-dev-boundary/ExceptionE1",
      "graveyard-dev-boundary/ExceptionE2",
      "graveyard-dev-boundary/ExceptionE3",
      "graveyard-dev-boundary/ExceptionE10",
      "graveyard-dev-boundary/ExceptionE5Profiles",
      "graveyard-dev-boundary/ExceptionE5ModelNarrate",
      "graveyard-dev-boundary/ExceptionE5ModelRites",
      "graveyard-prod-apply-compute/ExceptionE4",
      "graveyard-prod-apply-edge/ExceptionE6",
      "graveyard-dev-apply-compute/ExceptionE8",
      "graveyard-prod-apply-compute/ExceptionE8",
      "graveyard-plan-read-compute/ExceptionE8",
      "graveyard-dev-apply-edge/ExceptionE9",
      "graveyard-prod-apply-edge/ExceptionE9",
      "graveyard-prod-apply-ops/ExceptionE7",
      "graveyard-prod-boundary/ExceptionE1",
      "graveyard-prod-boundary/ExceptionE2",
      "graveyard-prod-boundary/ExceptionE3",
      "graveyard-prod-boundary/ExceptionE10",
      "graveyard-prod-boundary/ExceptionE5Profiles",
      "graveyard-prod-boundary/ExceptionE5ModelNarrate",
      "graveyard-prod-boundary/ExceptionE5ModelRites",
    ])
    error_message = "The exact-list rule must fail when an exception is added."
  }

  assert {
    condition     = toset(flatten([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-boundary" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "ExceptionE9", Effect = "Allow", Action = ["ec2:RunInstances"], Resource = "*" }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : flatten([try(x.stmt.Action, [])]) if startswith(x.stmt.Sid, "Exception")])) != toset(["xray:PutTraceSegments", "xray:PutTelemetryRecords", "cloudwatch:PutMetricData", "ecr:GetAuthorizationToken", "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "cloudfront:CreateOriginAccessControl", "cloudfront:GetOriginAccessControl", "cloudfront:ListOriginAccessControls", "cloudfront:UpdateOriginAccessControl", "cloudfront:DeleteOriginAccessControl", "states:ValidateStateMachineDefinition", "apigateway:POST", "apigateway:GET", "apigateway:DELETE", "logs:PutResourcePolicy", "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"])
    error_message = "The approved-actions rule must fail when an action is added."
  }
}

run "bad_sample_e5_widened_to_all_eu_regions" {
  command = plan

  # E5 widened to eu-* and foundation-model/*.

  assert {
    condition     = length(flatten([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-prod-boundary" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "ExceptionE5ModelNarrate", Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = ["arn:aws:bedrock:eu-*::foundation-model/*"] }] }) } }) : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : [for r in flatten([try(x.stmt.Resource, [])]) : "${x.policy}/${x.stmt.Sid}/${r}" if strcontains(r, "*")] if startswith(x.stmt.Sid, "ExceptionE5")])) == 1
    error_message = "E5 with eu-* must be caught."
  }
}
run "logs_put_resource_policy_is_for_state_machine_roles_only_never_a_ci_role" {
  command = plan
  assert {
    condition     = [for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : { policy = k, stmt = s } if s.Effect == "Allow"]]) : "${x.policy}/${x.stmt.Sid}" if contains(flatten([try(x.stmt.Action, [])]), "logs:PutResourcePolicy")] == ["graveyard-dev-boundary/ExceptionE10", "graveyard-prod-boundary/ExceptionE10"]
    error_message = "logs:PutResourcePolicy appears only in the boundaries' E10, never in a plan or apply policy."
  }
  assert {
    condition = alltrue([
      for e in ["dev", "prod"] :
      [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : s.Condition if s.Sid == "ExceptionE10"][0] == { ArnLike = { "aws:PrincipalArn" = "arn:aws:iam::123456789012:role/graveyard-${e}/graveyard-${e}-*-sfn" } }
    ])
    error_message = "E10 in the boundary is limited to the env's state machine roles."
  }
}
