# IAM rejects an ARN whose partition or service segment holds a wildcard ("MalformedPolicyDocument: Resource vendor
# must be fully qualified and cannot contain regexes"). Found at the first real apply: graveyard-dev-apply-guard and
# graveyard-prod-apply-guard were refused at CreatePolicy. Offline; real policy JSON. The bad-sample runs put one bad
# policy into the real set and show the rule catching it, so the rule cannot pass vacuously.
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
run "no_policy_has_a_wildcard_in_the_partition_or_service_segment" {
  command = plan
  assert {
    condition     = length([for x in flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, []), try(s.NotResource, [])]) : "${k}/${s.Sid}" if startswith(r, "arn:") && (can(regex("^arn:[^:]*[*?]", r)) || can(regex("^arn:[^:]*:[^:]*[*?]", r)))]]]) : x]) == 0
    error_message = "A Resource or NotResource ARN has * or ? in its partition or service segment. IAM rejects it at CreatePolicy."
  }
  assert {
    condition     = length(flatten([for k, p in aws_iam_policy.ci : [for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, []), try(s.NotResource, [])]) : r if startswith(r, "arn:")]]])) > 200
    error_message = "The rule must be looking at the real ARNs: expected well over 200 across the CI policies and boundaries."
  }
}
run "bad_sample_a_wildcard_service" {
  command = plan
  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Deny", Action = ["*"], Resource = ["arn:aws:*:*:*:*graveyard-prod-*"] }] }) } }) : [for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, []), try(s.NotResource, [])]) : "${k}/${s.Sid}" if startswith(r, "arn:") && (can(regex("^arn:[^:]*[*?]", r)) || can(regex("^arn:[^:]*:[^:]*[*?]", r)))]]]) : x], "graveyard-dev-apply-data/Bad")
    error_message = "The rule must catch this."
  }
}
run "bad_sample_a_wildcard_partition" {
  command = plan
  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Deny", Action = ["*"], Resource = ["arn:*:s3:::bucket/*"] }] }) } }) : [for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, []), try(s.NotResource, [])]) : "${k}/${s.Sid}" if startswith(r, "arn:") && (can(regex("^arn:[^:]*[*?]", r)) || can(regex("^arn:[^:]*:[^:]*[*?]", r)))]]]) : x], "graveyard-dev-apply-data/Bad")
    error_message = "The rule must catch this."
  }
}
run "bad_sample_a_question_mark_in_the_service" {
  command = plan
  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Deny", Action = ["*"], Resource = ["arn:aws:s3?:::bucket/*"] }] }) } }) : [for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, []), try(s.NotResource, [])]) : "${k}/${s.Sid}" if startswith(r, "arn:") && (can(regex("^arn:[^:]*[*?]", r)) || can(regex("^arn:[^:]*:[^:]*[*?]", r)))]]]) : x], "graveyard-dev-apply-data/Bad")
    error_message = "The rule must catch this."
  }
}
run "bad_sample_a_wildcard_service_in_not_resource" {
  command = plan
  assert {
    condition     = contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Deny", Action = ["*"], NotResource = ["arn:aws:*:eu-west-2::x"] }] }) } }) : [for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, []), try(s.NotResource, [])]) : "${k}/${s.Sid}" if startswith(r, "arn:") && (can(regex("^arn:[^:]*[*?]", r)) || can(regex("^arn:[^:]*:[^:]*[*?]", r)))]]]) : x], "graveyard-dev-apply-data/Bad")
    error_message = "The rule must catch this."
  }
}
run "bad_sample_wildcards_in_later_segments_pass" {
  command = plan
  assert {
    condition     = !contains([for x in flatten([for k, p in merge({ for k, p in aws_iam_policy.ci : k => { policy = p.policy } }, { "graveyard-dev-apply-data" = { policy = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "Bad", Effect = "Deny", Action = ["*"], Resource = ["arn:aws:lambda:*:*:function:graveyard-prod-*", "arn:aws:s3:::graveyard-*/*", "*"] }] }) } }) : [for s in jsondecode(p.policy).Statement : [for r in flatten([try(s.Resource, []), try(s.NotResource, [])]) : "${k}/${s.Sid}" if startswith(r, "arn:") && (can(regex("^arn:[^:]*[*?]", r)) || can(regex("^arn:[^:]*:[^:]*[*?]", r)))]]]) : x], "graveyard-dev-apply-data/Bad")
    error_message = "A wildcard in the region, account or resource segment is legal and must not be flagged."
  }
}
