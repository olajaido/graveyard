# Offline tests for the state module (INF-STATE-1..4, INF-STATE-9, INF-POL-1, INF-TEST-2).
# No credentials, no backend. The providers are mocked; the policies are jsonencode locals, so the
# real policy JSON is asserted. T3 showed that computed values (the random suffix, the KMS key ARN)
# are unknown at plan unless overridden with override_during = plan (decision T6.3).

mock_provider "aws" {}
mock_provider "random" {}

override_resource {
  target          = random_id.suffix
  override_during = plan
  values          = { hex = "abcd1234" }
}

override_resource {
  target          = aws_kms_key.state
  override_during = plan
  values = {
    id     = "00000000-0000-0000-0000-000000000000"
    key_id = "00000000-0000-0000-0000-000000000000"
    arn    = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
  }
}

variables {
  account_id = "123456789012"
  partition  = "aws"
  ci_role_arns = {
    plan = "arn:aws:iam::123456789012:role/graveyard-ci/graveyard-plan"
    apply = {
      dev  = "arn:aws:iam::123456789012:role/graveyard-ci/graveyard-dev-apply"
      prod = "arn:aws:iam::123456789012:role/graveyard-ci/graveyard-prod-apply"
    }
  }
}

run "bucket_settings" {
  command = plan

  assert {
    condition     = aws_s3_bucket.state.bucket == "graveyard-tfstate-abcd1234"
    error_message = "The bucket name must be graveyard-tfstate-<random suffix>."
  }

  assert {
    condition     = [for v in aws_s3_bucket_versioning.state.versioning_configuration : v.status][0] == "Enabled"
    error_message = "Versioning must be enabled."
  }

  assert {
    condition     = [for r in aws_s3_bucket_server_side_encryption_configuration.state.rule : [for d in r.apply_server_side_encryption_by_default : d.sse_algorithm][0]][0] == "aws:kms"
    error_message = "Default encryption must be SSE-KMS."
  }

  assert {
    condition     = [for r in aws_s3_bucket_server_side_encryption_configuration.state.rule : [for d in r.apply_server_side_encryption_by_default : d.kms_master_key_id][0]][0] == "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
    error_message = "Default encryption must use the state key."
  }

  assert {
    condition     = [for r in aws_s3_bucket_server_side_encryption_configuration.state.rule : r.bucket_key_enabled][0] == true
    error_message = "The S3 Bucket Key must be enabled."
  }

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.state.block_public_acls,
      aws_s3_bucket_public_access_block.state.block_public_policy,
      aws_s3_bucket_public_access_block.state.ignore_public_acls,
      aws_s3_bucket_public_access_block.state.restrict_public_buckets,
    ])
    error_message = "All four public access block settings must be on."
  }

  assert {
    condition     = [for r in aws_s3_bucket_ownership_controls.state.rule : r.object_ownership][0] == "BucketOwnerEnforced"
    error_message = "Object ownership must be BucketOwnerEnforced (ACLs disabled)."
  }
}

run "key_settings" {
  command = plan

  assert {
    condition     = aws_kms_key.state.enable_key_rotation == true
    error_message = "Key rotation must be enabled."
  }

  assert {
    condition     = aws_kms_key.state.deletion_window_in_days == 30
    error_message = "The deletion window must be 30 days."
  }

  assert {
    condition     = aws_kms_alias.state.name == "alias/graveyard-tfstate"
    error_message = "The alias must be alias/graveyard-tfstate."
  }
}

run "bucket_policy_denies_insecure_transport_and_wrong_encryption" {
  command = plan

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s.Sid] == ["DenyInsecureTransport", "DenyWrongEncryption", "DenyWrongKey"]
    error_message = "The bucket policy must have exactly the three deny statements."
  }

  assert {
    condition     = alltrue([for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s.Effect == "Deny" && s.Principal == "*"])
    error_message = "Every bucket policy statement must be a Deny for all principals."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s if s.Sid == "DenyInsecureTransport"][0].Condition.Bool["aws:SecureTransport"] == "false" &&
      [for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s if s.Sid == "DenyInsecureTransport"][0].Action == "s3:*" &&
      [for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s if s.Sid == "DenyInsecureTransport"][0].Resource == [
        "arn:aws:s3:::graveyard-tfstate-abcd1234",
        "arn:aws:s3:::graveyard-tfstate-abcd1234/*",
      ]
    )
    error_message = "The TLS-only statement must deny s3:* on the bucket and its objects when SecureTransport is false."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s if s.Sid == "DenyWrongEncryption"][0].Condition.StringNotEquals["s3:x-amz-server-side-encryption"] == "aws:kms" &&
      [for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s if s.Sid == "DenyWrongEncryption"][0].Action == "s3:PutObject"
    )
    error_message = "Writes must be denied unless they ask for SSE-KMS."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s if s.Sid == "DenyWrongKey"][0].Condition.StringNotEqualsIfExists["s3:x-amz-server-side-encryption-aws-kms-key-id"] == "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
    )
    error_message = "Writes must be denied unless they use the state key."
  }
}

run "key_policy_grants_only_ci_roles_via_s3" {
  command = plan

  assert {
    condition     = [for s in jsondecode(aws_kms_key_policy.state.policy).Statement : s.Sid] == ["AccountAdmin", "CiUseViaS3"]
    error_message = "The key policy must have exactly the account statement and the CI statement."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_kms_key_policy.state.policy).Statement : s if s.Sid == "AccountAdmin"][0].Principal.AWS == "arn:aws:iam::123456789012:root" &&
      [for s in jsondecode(aws_kms_key_policy.state.policy).Statement : s if s.Sid == "AccountAdmin"][0].Action == "kms:*"
    )
    error_message = "The account-root statement must be the standard one."
  }

  assert {
    condition = [for s in jsondecode(aws_kms_key_policy.state.policy).Statement : s if s.Sid == "CiUseViaS3"][0].Principal.AWS == [
      "arn:aws:iam::123456789012:role/graveyard-ci/graveyard-plan",
      "arn:aws:iam::123456789012:role/graveyard-ci/graveyard-dev-apply",
      "arn:aws:iam::123456789012:role/graveyard-ci/graveyard-prod-apply",
    ]
    error_message = "Only the plan role and the two apply roles may use the key."
  }

  assert {
    condition     = [for s in jsondecode(aws_kms_key_policy.state.policy).Statement : s if s.Sid == "CiUseViaS3"][0].Action == ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    error_message = "The CI roles may use exactly the four KMS actions."
  }

  assert {
    condition     = [for s in jsondecode(aws_kms_key_policy.state.policy).Statement : s if s.Sid == "CiUseViaS3"][0].Condition.StringEquals["kms:ViaService"] == "s3.eu-west-2.amazonaws.com"
    error_message = "The CI roles may use the key only through S3 in eu-west-2."
  }
}

run "lifecycle_rules" {
  command = plan

  assert {
    condition     = toset([for r in aws_s3_bucket_lifecycle_configuration.state.rule : r.id]) == toset(["state-versions-envs", "state-versions-bootstrap", "plans", "housekeeping"])
    error_message = "The lifecycle configuration must have exactly the four rules."
  }

  assert {
    condition     = alltrue([for r in aws_s3_bucket_lifecycle_configuration.state.rule : r.status == "Enabled"])
    error_message = "Every lifecycle rule must be enabled."
  }

  assert {
    condition = (
      [for r in aws_s3_bucket_lifecycle_configuration.state.rule : r if r.id == "plans"][0].expiration[0].days == 7 &&
      [for r in aws_s3_bucket_lifecycle_configuration.state.rule : r if r.id == "plans"][0].filter[0].prefix == "plans/" &&
      [for r in aws_s3_bucket_lifecycle_configuration.state.rule : r if r.id == "plans"][0].noncurrent_version_expiration[0].noncurrent_days == 1
    )
    error_message = "Saved plans must expire after 7 days, and their old versions after 1 day."
  }

  assert {
    condition = alltrue([
      for r in aws_s3_bucket_lifecycle_configuration.state.rule :
      r.noncurrent_version_expiration[0].noncurrent_days == 90 && r.noncurrent_version_expiration[0].newer_noncurrent_versions == 10
      if r.id == "state-versions-envs" || r.id == "state-versions-bootstrap"
    ])
    error_message = "Old state versions must expire after 90 days, keeping the newest 10."
  }

  assert {
    condition = (
      [for r in aws_s3_bucket_lifecycle_configuration.state.rule : r if r.id == "housekeeping"][0].expiration[0].expired_object_delete_marker == true &&
      [for r in aws_s3_bucket_lifecycle_configuration.state.rule : r if r.id == "housekeeping"][0].abort_incomplete_multipart_upload[0].days_after_initiation == 7
    )
    error_message = "Housekeeping must remove expired delete markers and abort multipart uploads after 7 days."
  }
}

run "lifecycle_values_follow_the_variables" {
  command = plan

  variables {
    state_noncurrent_days = 30
    state_noncurrent_keep = 3
    plans_expiry_days     = 3
  }

  assert {
    condition = (
      [for r in aws_s3_bucket_lifecycle_configuration.state.rule : r if r.id == "plans"][0].expiration[0].days == 3 &&
      [for r in aws_s3_bucket_lifecycle_configuration.state.rule : r if r.id == "state-versions-envs"][0].noncurrent_version_expiration[0].noncurrent_days == 30 &&
      [for r in aws_s3_bucket_lifecycle_configuration.state.rule : r if r.id == "state-versions-envs"][0].noncurrent_version_expiration[0].newer_noncurrent_versions == 3
    )
    error_message = "The lifecycle values must come from the variables."
  }
}

run "partition_is_taken_from_the_input" {
  command = plan

  variables {
    partition = "aws-us-gov"
  }

  assert {
    condition     = [for s in jsondecode(aws_kms_key_policy.state.policy).Statement : s if s.Sid == "AccountAdmin"][0].Principal.AWS == "arn:aws-us-gov:iam::123456789012:root"
    error_message = "The partition must come from the input."
  }

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s if s.Sid == "DenyInsecureTransport"][0].Resource[0] == "arn:aws-us-gov:s3:::graveyard-tfstate-abcd1234"
    error_message = "The bucket ARN must use the input partition."
  }
}

run "plans_expiry_above_seven_days_is_rejected" {
  command = plan

  variables {
    plans_expiry_days = 8
  }

  expect_failures = [var.plans_expiry_days]
}

run "plans_expiry_of_zero_is_rejected" {
  command = plan

  variables {
    plans_expiry_days = 0
  }

  expect_failures = [var.plans_expiry_days]
}

run "other_regions_are_rejected" {
  command = plan

  variables {
    region = "us-east-1"
  }

  expect_failures = [var.region]
}

run "malformed_account_id_is_rejected" {
  command = plan

  variables {
    account_id = "12345"
  }

  expect_failures = [var.account_id]
}

run "bucket_prefix_must_be_a_graveyard_name" {
  command = plan

  variables {
    bucket_name_prefix = "tfstate"
  }

  expect_failures = [var.bucket_name_prefix]
}
