# The plan role's policies (INF-PLAN-1..4, INF-REG-2, decisions C2 and C5). The plan role is reachable
# from a pull-request branch, so its writes are limited to plans/* and the env lock keys.

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

run "the_plan_role_has_exactly_its_policies_attached" {
  command = plan

  assert {
    condition     = toset(keys({ for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") })) == toset(["graveyard-plan-state", "graveyard-plan-read-iam", "graveyard-plan-read-compute", "graveyard-plan-read-data", "graveyard-plan-read-edge", "graveyard-plan-read-edge-extra", "graveyard-plan-read-ops", "graveyard-plan-guard"])
    error_message = "Unexpected set of plan policies."
  }

  assert {
    condition     = toset(keys(aws_iam_role_policy_attachment.plan)) == toset(keys({ for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") }))
    error_message = "Every plan policy must be attached to the plan role."
  }

  assert {
    condition     = alltrue([for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : p.path == "/graveyard-ci/" && p.name == k])
    error_message = "Policies must sit on the CI path and be named by their key."
  }
}

run "the_only_writes_are_plans_and_the_lock_keys" {
  command = plan

  assert {
    condition = toset(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : flatten([s.Resource])
        if s.Effect == "Allow" && contains(flatten([try(s.Action, [])]), "s3:PutObject")
      ]
      ])) == toset([
      "arn:aws:s3:::graveyard-tfstate-abcd1234/plans/*",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/dev/terraform.tfstate.tflock",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/prod/terraform.tfstate.tflock",
    ])
    error_message = "s3:PutObject may be allowed only on plans/* and the two lock keys (INF-PLAN-3)."
  }

  assert {
    condition = toset(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : flatten([s.Resource])
        if s.Effect == "Allow" && contains(flatten([try(s.Action, [])]), "s3:DeleteObject")
      ]
      ])) == toset([
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/dev/terraform.tfstate.tflock",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/prod/terraform.tfstate.tflock",
    ])
    error_message = "s3:DeleteObject may be allowed only on the two lock keys."
  }

  assert {
    condition = alltrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : [
          for a in flatten([try(s.Action, [])]) : startswith(a, "s3:Get") || startswith(a, "s3:List") || startswith(a, "s3:PutObject") || startswith(a, "s3:DeleteObject")
          if startswith(a, "s3:")
        ]
        if s.Effect == "Allow"
      ]
    ]))
    error_message = "The plan role may allow only S3 reads, plan writes and lock-key writes."
  }
}

run "state_reads_stay_inside_the_state_bucket_and_never_touch_bootstrap" {
  command = plan

  assert {
    condition = alltrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : [
          for r in flatten([s.Resource]) : startswith(r, "arn:aws:s3:::graveyard-tfstate-abcd1234") && !strcontains(r, "/bootstrap/")
        ]
        if s.Effect == "Allow" && contains(flatten([try(s.Action, [])]), "s3:GetObject")
      ]
    ]))
    error_message = "s3:GetObject must be allowed only on state-bucket objects outside bootstrap/ (INF-PLAN-2, INF-PLAN-4)."
  }

  assert {
    condition = toset(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : flatten([s.Resource])
        if s.Effect == "Allow" && contains(flatten([try(s.Action, [])]), "s3:GetObject")
      ]
      ])) == toset([
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/dev/terraform.tfstate",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/prod/terraform.tfstate",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/dev/terraform.tfstate.tflock",
      "arn:aws:s3:::graveyard-tfstate-abcd1234/envs/prod/terraform.tfstate.tflock",
    ])
    error_message = "The plan role reads the two env state keys and their lock keys, and nothing else."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-guard"].policy).Statement : s
      if s.Sid == "DenyBootstrapState"
      ][0] == {
      Sid      = "DenyBootstrapState"
      Effect   = "Deny"
      Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"]
      Resource = ["arn:aws:s3:::graveyard-tfstate-abcd1234/bootstrap/*"]
    }
    error_message = "The guard must explicitly deny every access to bootstrap/*."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-guard"].policy).Statement : s
      if s.Sid == "DenyObjectReadOutsideStateBucket"
      ][0] == {
      Sid         = "DenyObjectReadOutsideStateBucket"
      Effect      = "Deny"
      Action      = ["s3:GetObject", "s3:GetObjectVersion"]
      NotResource = ["arn:aws:s3:::graveyard-tfstate-abcd1234/*"]
    }
    error_message = "The guard must deny object reads outside the state bucket."
  }
}

run "kms_is_limited_to_the_state_key_through_s3" {
  command = plan

  assert {
    condition = toset(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : flatten([s.Resource])
        if s.Effect == "Allow" && anytrue([for a in flatten([try(s.Action, [])]) : contains(["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:ReEncrypt*"], a)])
      ]
    ])) == toset(["arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"])
    error_message = "kms:Decrypt, Encrypt and GenerateDataKey may be allowed only on the state key (INF-PLAN-2)."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-state"].policy).Statement : s
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
    error_message = "The key statement must allow exactly four actions, through S3 only, on a key tagged Project=graveyard."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-guard"].policy).Statement : s
      if s.Sid == "DenyDecryptOutsideStateKey"
      ][0] == {
      Sid         = "DenyDecryptOutsideStateKey"
      Effect      = "Deny"
      Action      = ["kms:Decrypt"]
      NotResource = ["arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"]
    }
    error_message = "The guard must deny kms:Decrypt on every key except the state key."
  }
}

run "the_plan_role_never_reads_secret_values" {
  command = plan

  assert {
    condition = alltrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : [
          for a in flatten([try(s.Action, [])]) : contains(["secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy", "secretsmanager:ListSecretVersionIds"], a)
          if startswith(a, "secretsmanager:")
        ]
        if s.Effect == "Allow"
      ]
    ]))
    error_message = "The plan role may read secret metadata only, never a value (INF-PLAN-2)."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-guard"].policy).Statement : s
      if s.Sid == "DenySecretValues"
      ][0] == {
      Sid      = "DenySecretValues"
      Effect   = "Deny"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = "*"
    }
    error_message = "The guard must deny secretsmanager:GetSecretValue everywhere."
  }
}

run "the_state_and_iam_read_policies_have_no_star_resource" {
  command = plan

  assert {
    condition = !anytrue(flatten([
      for k in ["graveyard-plan-state", "graveyard-plan-read-iam"] : [
        for s in jsondecode(aws_iam_policy.ci[k].policy).Statement : contains(flatten([try(s.Resource, [])]), "*")
        if s.Effect == "Allow"
      ]
    ]))
    error_message = "These policies must name their resources."
  }

  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-read-iam"].policy).Statement : [
        for a in flatten([s.Action]) : startswith(a, "iam:Get") || startswith(a, "iam:List")
      ]
    ]))
    error_message = "The IAM read policy may allow only iam:Get* and iam:List* actions."
  }

  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-read-iam"].policy).Statement : [
        for r in flatten([s.Resource]) : strcontains(r, "/graveyard-dev/graveyard-dev-") || strcontains(r, "/graveyard-prod/graveyard-prod-")
      ]
    ]))
    error_message = "IAM reads must be limited to the workload paths and names of the two envs."
  }
}

run "the_region_deny_is_in_the_guard" {
  command = plan

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-guard"].policy).Statement : s
      if s.Sid == "DenyOutsideRegion"
      ][0] == {
      Sid       = "DenyOutsideRegion"
      Effect    = "Deny"
      NotAction = concat(["iam:*", "sts:*", "cloudfront:*", "wafv2:*", "acm:*", "budgets:*", "ce:*", "s3:ListAllMyBuckets", "s3:GetBucketLocation"], ["route53:ChangeResourceRecordSets", "route53:GetChange", "route53:GetHostedZone", "route53:ListResourceRecordSets", "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource", "cloudwatch:UntagResource", "cloudwatch:ListTagsForResource", "cloudwatch:DescribeAlarms", "sns:CreateTopic", "sns:DeleteTopic", "sns:SetTopicAttributes", "sns:TagResource", "sns:UntagResource", "sns:GetTopicAttributes", "sns:ListTagsForResource"])
      Resource  = "*"
      Condition = { StringNotEquals = { "aws:RequestedRegion" = "eu-west-2" }, Bool = { "aws:ViaAWSService" = "false" } }
    }
    error_message = "The guard must deny every action outside eu-west-2 except the global services."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.ci["graveyard-plan-guard"].policy).Statement : s
      if s.Sid == "DenyGlobalOutsideUsEast1"
      ][0] == {
      Sid       = "DenyGlobalOutsideUsEast1"
      Effect    = "Deny"
      Action    = concat(["cloudfront:*", "wafv2:*", "acm:*"], ["route53:ChangeResourceRecordSets", "route53:GetChange", "route53:GetHostedZone", "route53:ListResourceRecordSets", "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource", "cloudwatch:UntagResource", "cloudwatch:ListTagsForResource", "cloudwatch:DescribeAlarms", "sns:CreateTopic", "sns:DeleteTopic", "sns:SetTopicAttributes", "sns:TagResource", "sns:UntagResource", "sns:GetTopicAttributes", "sns:ListTagsForResource"])
      Resource  = "*"
      Condition = { StringNotEquals = { "aws:RequestedRegion" = ["eu-west-2", "us-east-1"] }, Bool = { "aws:ViaAWSService" = "false" } }
    }
    error_message = "CloudFront, WAF and ACM may use only eu-west-2 and us-east-1."
  }
}

run "a_single_env_removes_the_other_envs_resources" {
  command = plan

  variables {
    envs = ["prod"]
  }

  assert {
    condition = !anytrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : [
          for r in flatten([try(s.Resource, [])]) : strcontains(r, "dev")
        ]
      ]
    ]))
    error_message = "With envs = [prod] no policy may name a dev resource."
  }
}

run "the_partition_comes_from_the_input" {
  command = plan

  variables {
    partition         = "aws-us-gov"
    state_kms_key_arn = "arn:aws-us-gov:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
    route53_zone_id   = "Z0123456789ABCDEFGHIJ"
  }

  assert {
    condition = alltrue(flatten([
      for k, p in { for k2, p2 in aws_iam_policy.ci : k2 => p2 if startswith(k2, "graveyard-plan-") } : [
        for s in jsondecode(p.policy).Statement : [
          for r in flatten([try(s.Resource, s.NotResource)]) : r == "*" || startswith(r, "arn:aws-us-gov:")
        ]
      ]
    ]))
    error_message = "Every ARN must use the input partition."
  }
}

run "a_ci_path_that_is_not_a_graveyard_path_is_rejected" {
  command = plan

  variables {
    ci_path = "/other/"
  }

  expect_failures = [var.ci_path]
}

run "an_unknown_env_is_rejected" {
  command = plan

  variables {
    envs = ["staging"]
  }

  expect_failures = [var.envs]
}

run "an_empty_env_set_is_rejected" {
  command = plan

  variables {
    envs = []
  }

  expect_failures = [var.envs]
}

run "a_state_bucket_without_a_graveyard_name_is_rejected" {
  command = plan

  variables {
    state_bucket_name = "tfstate"
  }

  expect_failures = [var.state_bucket_name]
}
