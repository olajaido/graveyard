# Trust policy of the plan role (INF-OIDC-2, INF-OIDC-3, INF-OIDC-5, INF-OIDC-6). Offline: no
# credentials, no backend, and the policy is a jsonencode local, so the real JSON is asserted.

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

run "plan_trust_has_exactly_the_two_subjects" {
  command = plan

  assert {
    condition     = length(jsondecode(aws_iam_role.plan.assume_role_policy).Statement) == 1
    error_message = "The trust policy must have exactly one statement."
  }

  assert {
    condition = (
      jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Effect == "Allow" &&
      jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Action == "sts:AssumeRoleWithWebIdentity"
    )
    error_message = "Only sts:AssumeRoleWithWebIdentity may be allowed."
  }

  assert {
    condition     = jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Principal == { Federated = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
    error_message = "The only principal must be the GitHub OIDC provider."
  }

  assert {
    condition     = keys(jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition) == ["StringEquals"]
    error_message = "The condition must use StringEquals only (no StringLike)."
  }

  assert {
    condition     = keys(jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals) == ["token.actions.githubusercontent.com:aud", "token.actions.githubusercontent.com:sub"]
    error_message = "The condition must constrain the audience and the subject, and nothing else."
  }

  assert {
    condition     = jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "The audience must be sts.amazonaws.com."
  }

  assert {
    condition = jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == [
      "repo:olajaido@102736714/graveyard@1443508961:pull_request",
      "repo:olajaido@102736714/graveyard@1443508961:ref:refs/heads/main",
    ]
    error_message = "The plan role must trust exactly the pull_request and main subjects (decision C2)."
  }
}

run "no_wildcard_in_any_subject" {
  command = plan

  assert {
    condition = !anytrue([
      for s in jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] :
      can(regex("[*?]", s))
    ])
    error_message = "No subject may contain a wildcard."
  }
}

run "session_lasts_one_hour_and_the_role_sits_on_the_ci_path" {
  command = plan

  assert {
    condition     = aws_iam_role.plan.max_session_duration == 3600
    error_message = "The maximum session duration must be 1 hour (INF-OIDC-6)."
  }

  assert {
    condition     = aws_iam_role.plan.name == "graveyard-plan" && aws_iam_role.plan.path == "/graveyard-ci/"
    error_message = "The plan role must be graveyard-plan on /graveyard-ci/."
  }
}

run "subjects_follow_the_repository_variables" {
  command = plan

  variables {
    repo_owner    = "someone-else"
    repo_name     = "other-repo"
    repo_owner_id = "42"
    repo_id       = "7"
  }

  assert {
    condition = jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == [
      "repo:someone-else@42/other-repo@7:pull_request",
      "repo:someone-else@42/other-repo@7:ref:refs/heads/main",
    ]
    error_message = "Every subject must be built from the owner, the repository and both numeric IDs (INF-OIDC-5)."
  }
}

run "a_wildcard_in_the_owner_is_rejected" {
  command = plan

  variables {
    repo_owner = "bad*owner"
  }

  expect_failures = [var.repo_owner]
}

run "a_wildcard_in_the_repository_name_is_rejected" {
  command = plan

  variables {
    repo_name = "graveyard*"
  }

  expect_failures = [var.repo_name]
}

run "a_subject_separator_in_the_owner_is_rejected" {
  command = plan

  variables {
    repo_owner = "olajaido/graveyard:environment:prod"
  }

  expect_failures = [var.repo_owner]
}

# The repository uses GitHub's immutable subject (T24): the IDs are part of every subject, there is no old-format
# subject, and the IDs are digits only.
run "every_trusted_subject_is_in_the_immutable_format" {
  command = plan
  assert {
    condition = alltrue(flatten([
      [for s in jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] : can(regex("^repo:olajaido@102736714/graveyard@1443508961:(pull_request|ref:refs/heads/main)$", s))],
      [for e in ["dev", "prod"] : can(regex("^repo:olajaido@102736714/graveyard@1443508961:environment:${e}$", jsondecode(aws_iam_role.apply[e].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]))],
    ]))
    error_message = "Every subject, plan and apply, must be repo:<owner>@<owner id>/<repo>@<repo id>:<context>."
  }
  assert {
    condition = !anytrue(flatten([
      [for s in jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] : can(regex("^repo:olajaido/graveyard:", s))],
      [for e in ["dev", "prod"] : can(regex("^repo:olajaido/graveyard:", jsondecode(aws_iam_role.apply[e].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]))],
    ]))
    error_message = "The old subject format (no IDs) must not be trusted."
  }
  assert {
    condition = alltrue([
      for e in ["dev", "prod"] : keys(jsondecode(aws_iam_role.apply[e].assume_role_policy).Statement[0].Condition) == ["StringEquals"]
    ])
    error_message = "The apply trust policies must use StringEquals only."
  }
}
run "a_wildcard_in_the_owner_id_is_rejected" {
  command = plan
  variables {
    repo_owner_id = "1*"
  }
  expect_failures = [var.repo_owner_id]
}
run "a_wildcard_in_the_repository_id_is_rejected" {
  command = plan
  variables {
    repo_id = "14?3508961"
  }
  expect_failures = [var.repo_id]
}
run "a_non_numeric_or_empty_id_is_rejected" {
  command = plan
  variables {
    repo_owner_id = ""
    repo_id       = "12ab"
  }
  expect_failures = [var.repo_owner_id, var.repo_id]
}
run "a_subject_separator_in_an_id_is_rejected" {
  command = plan
  variables {
    repo_id = "1:environment:prod"
  }
  expect_failures = [var.repo_id]
}
