# infra-edge permissions (EDGE-IAM-1 to EDGE-IAM-7, EDGE-TEST-4, exceptions E11 and E12, decision R4). Offline; real policy JSON.
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
  route53_zone_id   = "Z0123456789ABCDEFGHIJ"
}
# E11: the actions the CI roles may also use in us-east-1. Written out in full so a change must be a reviewed change here.
run "e11_is_in_the_three_guards_and_in_no_boundary" {
  command = plan
  assert {
    condition = alltrue([
      for k in ["graveyard-plan-guard", "graveyard-dev-apply-guard", "graveyard-prod-apply-guard"] : (
        [for s in jsondecode(aws_iam_policy.ci[k].policy).Statement : s if s.Sid == "DenyOutsideRegion"][0].NotAction == concat(
          ["iam:*", "sts:*", "cloudfront:*", "wafv2:*", "acm:*", "budgets:*", "ce:*", "s3:ListAllMyBuckets", "s3:GetBucketLocation"],
          ["route53:ChangeResourceRecordSets", "route53:GetChange", "route53:GetHostedZone", "route53:ListResourceRecordSets", "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource", "cloudwatch:UntagResource", "cloudwatch:ListTagsForResource", "cloudwatch:DescribeAlarms", "sns:CreateTopic", "sns:DeleteTopic", "sns:SetTopicAttributes", "sns:TagResource", "sns:UntagResource", "sns:GetTopicAttributes", "sns:ListTagsForResource"],
        ) &&
        [for s in jsondecode(aws_iam_policy.ci[k].policy).Statement : s if s.Sid == "DenyGlobalOutsideUsEast1"][0].Condition == { StringNotEquals = { "aws:RequestedRegion" = ["eu-west-2", "us-east-1"] } }
      )
    ])
    error_message = "E11 must add exactly these actions to the region exemption of the plan guard and both apply guards, still limited to eu-west-2 and us-east-1."
  }
  assert {
    condition = !anytrue(flatten([
      for e in ["dev", "prod"] : [
        for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-boundary"].policy).Statement : [
          for a in flatten([try(s.NotAction, []), try(s.Action, [])]) : contains(["route53:ChangeResourceRecordSets", "route53:GetChange", "route53:GetHostedZone", "route53:ListResourceRecordSets", "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource", "cloudwatch:UntagResource", "cloudwatch:ListTagsForResource", "cloudwatch:DescribeAlarms", "sns:CreateTopic", "sns:DeleteTopic", "sns:SetTopicAttributes", "sns:TagResource", "sns:UntagResource", "sns:GetTopicAttributes", "sns:ListTagsForResource"], a)
        ]
      ]
    ]))
    error_message = "A workload boundary must not contain any E11 action (infra-edge R9)."
  }
}
# R9: the boundaries are 60 characters under the 6,144 limit, so they must not change. 6,066 and 6,084 are the sizes before infra-edge.
run "the_boundaries_have_not_grown" {
  command = plan
  assert {
    condition     = length(aws_iam_policy.ci["graveyard-dev-boundary"].policy) == 6066 && length(aws_iam_policy.ci["graveyard-prod-boundary"].policy) == 6084
    error_message = "A boundary changed size. infra-edge must not touch it (design 12.1); if the change is intended, update this test and re-check the 6,144 limit."
  }
}
run "e12_is_the_exact_zone_and_this_envs_record_names" {
  command = plan
  assert {
    condition = [for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-edge-extra"].policy).Statement : s if s.Sid == "ExceptionE12"][0] == {
      Sid      = "ExceptionE12"
      Effect   = "Allow"
      Action   = ["route53:ChangeResourceRecordSets"]
      Resource = ["arn:aws:route53:::hostedzone/Z0123456789ABCDEFGHIJ"]
      Condition = {
        "ForAllValues:StringLike" = { "route53:ChangeResourceRecordSetsNormalizedRecordNames" = ["dev.lastrites.dev", "api.dev.lastrites.dev", "_*.dev.lastrites.dev"] }
        "ForAllValues:StringEquals" = {
          "route53:ChangeResourceRecordSetsRecordTypes" = ["A", "AAAA", "CNAME"]
          "route53:ChangeResourceRecordSetsActions"     = ["CREATE", "UPSERT", "DELETE"]
        }
        Null = {
          "route53:ChangeResourceRecordSetsNormalizedRecordNames" = "false"
          "route53:ChangeResourceRecordSetsRecordTypes"           = "false"
          "route53:ChangeResourceRecordSetsActions"               = "false"
        }
      }
    }
    error_message = "The dev E12 statement must be exactly the zone, the dev names, A, AAAA and CNAME, and CREATE, UPSERT and DELETE."
  }
  assert {
    condition = [for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-edge-extra"].policy).Statement : s if s.Sid == "ExceptionE12"][0] == {
      Sid      = "ExceptionE12"
      Effect   = "Allow"
      Action   = ["route53:ChangeResourceRecordSets"]
      Resource = ["arn:aws:route53:::hostedzone/Z0123456789ABCDEFGHIJ"]
      Condition = {
        "ForAllValues:StringLike" = { "route53:ChangeResourceRecordSetsNormalizedRecordNames" = ["lastrites.dev", "api.lastrites.dev", "_*.lastrites.dev", "www.lastrites.dev"] }
        "ForAllValues:StringEquals" = {
          "route53:ChangeResourceRecordSetsRecordTypes" = ["A", "AAAA", "CNAME"]
          "route53:ChangeResourceRecordSetsActions"     = ["CREATE", "UPSERT", "DELETE"]
        }
        Null = {
          "route53:ChangeResourceRecordSetsNormalizedRecordNames" = "false"
          "route53:ChangeResourceRecordSetsRecordTypes"           = "false"
          "route53:ChangeResourceRecordSetsActions"               = "false"
        }
      }
    }
    error_message = "The prod E12 statement must be exactly the zone, the prod names (apex, api, www, validation), A, AAAA and CNAME, and CREATE, UPSERT and DELETE."
  }
  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : !anytrue(flatten([
        for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-edge-extra"].policy).Statement : [for a in flatten([s.Action]) : startswith(a, "route53:") && !contains(["route53:ChangeResourceRecordSets", "route53:GetChange", "route53:GetHostedZone", "route53:ListResourceRecordSets"], a)]
      ]))
    ])
    error_message = "Only these four Route 53 actions may be allowed, and never on another zone."
  }
}
# R4 (EDGE-IAM-3): prod can never change a dev record, whatever its Allow says. The dev guard has no such statement.
run "the_prod_apply_role_is_explicitly_denied_dev_records" {
  command = plan
  assert {
    condition = [for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-guard"].policy).Statement : s if s.Sid == "DenyProdChangingDevRecords"][0] == {
      Sid       = "DenyProdChangingDevRecords"
      Effect    = "Deny"
      Action    = ["route53:ChangeResourceRecordSets"]
      Resource  = "*"
      Condition = { "ForAnyValue:StringLike" = { "route53:ChangeResourceRecordSetsNormalizedRecordNames" = ["*dev.lastrites.dev"] } }
    }
    error_message = "The prod guard must deny ChangeResourceRecordSets when any record name matches *dev.lastrites.dev."
  }
  assert {
    condition     = length([for s in jsondecode(aws_iam_policy.ci["graveyard-dev-apply-guard"].policy).Statement : s if s.Sid == "DenyProdChangingDevRecords"]) == 0 && length([for s in jsondecode(aws_iam_policy.ci["graveyard-plan-guard"].policy).Statement : s if s.Sid == "DenyProdChangingDevRecords"]) == 0
    error_message = "Only the prod apply guard carries the deny."
  }
  # The pattern in the policy, as a regular expression, must not catch a name prod is allowed to change, and must catch dev's.
  assert {
    condition = !anytrue([
      for n in ["lastrites.dev", "api.lastrites.dev", "www.lastrites.dev", "_0123456789abcdef0123456789abcdef.lastrites.dev", "_0123456789abcdef0123456789abcdef.api.lastrites.dev"] : can(regex("^${replace(replace([for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-guard"].policy).Statement : s if s.Sid == "DenyProdChangingDevRecords"][0].Condition["ForAnyValue:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"][0], ".", "\\."), "*", ".*")}$", n))
    ])
    error_message = "The deny pattern must not match a prod name."
  }
  assert {
    condition = alltrue([
      for n in ["dev.lastrites.dev", "api.dev.lastrites.dev", "_0123456789abcdef0123456789abcdef.dev.lastrites.dev", "_0123456789abcdef0123456789abcdef.api.dev.lastrites.dev"] : can(regex("^${replace(replace([for s in jsondecode(aws_iam_policy.ci["graveyard-prod-apply-guard"].policy).Statement : s if s.Sid == "DenyProdChangingDevRecords"][0].Condition["ForAnyValue:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"][0], ".", "\\."), "*", ".*")}$", n))
    ])
    error_message = "The deny pattern must match the dev apex, the dev API and the dev validation names."
  }
}
# R2: no response-headers, cache or origin-request policy may be created, changed or deleted by a CI role.
run "no_cloudfront_policy_can_be_created_changed_or_deleted" {
  command = plan
  assert {
    condition = !anytrue(flatten([
      for k, p in aws_iam_policy.ci : [
        for s in jsondecode(p.policy).Statement : [
          for a in flatten([try(s.Action, [])]) : s.Effect == "Allow" && can(regex("^cloudfront:(Create|Update|Delete).*(ResponseHeadersPolicy|CachePolicy|OriginRequestPolicy)", a))
        ]
      ]
    ]))
    error_message = "No CI role may create, update or delete a CloudFront response-headers, cache or origin-request policy (INF-SHARED-3, R2, R11)."
  }
}
run "the_site_objects_and_the_us_east_1_alarms_and_topic_are_scoped_to_the_env" {
  command = plan
  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : (
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-edge-extra"].policy).Statement : s if s.Sid == "SiteObjects"][0] == {
          Sid      = "SiteObjects"
          Effect   = "Allow"
          Action   = ["s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
          Resource = ["arn:aws:s3:::graveyard-${e}-site-*/*"]
        } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-edge-extra"].policy).Statement : s if s.Sid == "EdgeAlarms"][0] == {
          Sid      = "EdgeAlarms"
          Effect   = "Allow"
          Action   = ["cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource", "cloudwatch:UntagResource", "cloudwatch:ListTagsForResource"]
          Resource = ["arn:aws:cloudwatch:us-east-1:123456789012:alarm:graveyard-${e}-*"]
        } &&
        [for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-edge-extra"].policy).Statement : s if s.Sid == "EdgeTopic"][0] == {
          Sid      = "EdgeTopic"
          Effect   = "Allow"
          Action   = ["sns:CreateTopic", "sns:DeleteTopic", "sns:SetTopicAttributes", "sns:TagResource", "sns:UntagResource", "sns:GetTopicAttributes", "sns:ListTagsForResource"]
          Resource = ["arn:aws:sns:us-east-1:123456789012:graveyard-${e}-*"]
        }
      )
    ])
    error_message = "SiteObjects, EdgeAlarms and EdgeTopic must be exactly these actions on this env's graveyard-<env> names (object writes only on -site- buckets, alarms and topic in us-east-1)."
  }
  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : !anytrue(flatten([
        for s in jsondecode(aws_iam_policy.ci["graveyard-${e}-apply-edge-extra"].policy).Statement : [for r in flatten([s.Resource]) : strcontains(r, "graveyard-${e == "dev" ? "prod" : "dev"}")]
      ]))
    ])
    error_message = "An edge-extra policy must not name the other env."
  }
}
run "the_new_policies_fit_the_limits" {
  command = plan
  assert {
    condition     = alltrue([for k, p in aws_iam_policy.ci : length(p.policy) <= 6144])
    error_message = "A managed policy must be at most 6,144 characters."
  }
  # R9: 8 managed policies per apply role and 8 for the plan role; the quota is 10.
  assert {
    condition = (
      length([for k, a in aws_iam_role_policy_attachment.apply : k if startswith(k, "dev/")]) == 8 &&
      length([for k, a in aws_iam_role_policy_attachment.apply : k if startswith(k, "prod/")]) == 8 &&
      length(aws_iam_role_policy_attachment.plan) == 8
    )
    error_message = "Each apply role must have 8 managed policies and the plan role 8 (limit 10)."
  }
}
run "the_plan_role_reads_the_zone_and_the_edge_alarms_and_writes_nothing_new" {
  command = plan
  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-read-edge-extra"].policy).Statement : [for a in flatten([s.Action]) : can(regex("(?i)^[a-z0-9-]+:(get|list|describe)", a))]
    ]))
    error_message = "The plan role's edge policy may hold only reads."
  }
  assert {
    condition     = [for s in jsondecode(aws_iam_policy.ci["graveyard-plan-read-edge-extra"].policy).Statement : s if s.Sid == "Route53Read"][0].Resource == ["arn:aws:route53:::hostedzone/Z0123456789ABCDEFGHIJ"]
    error_message = "The plan role reads records of the one zone only."
  }
}
run "a_bad_zone_id_is_rejected" {
  command = plan
  variables {
    route53_zone_id = "z-lower-case"
  }
  expect_failures = [var.route53_zone_id]
}
run "a_bad_domain_is_rejected" {
  command = plan
  variables {
    edge_domain_name = "*.lastrites.dev"
  }
  expect_failures = [var.edge_domain_name]
}
