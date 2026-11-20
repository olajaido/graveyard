# Offline tests for the data module (SB-DATA-1, SB-DATA-4, SB-DATA-5, SB-CFG-1).
mock_provider "aws" {}
override_resource {
  target          = aws_kms_key.app
  override_during = plan
  values = {
    arn    = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
    key_id = "00000000-0000-0000-0000-000000000000"
  }
}
override_resource {
  target          = aws_s3_bucket.artefacts
  override_during = plan
  values = {
    arn = "arn:aws:s3:::graveyard-dev-artefacts-20260101"
    id  = "graveyard-dev-artefacts-20260101"
  }
}
override_resource {
  target          = aws_dynamodb_table.data
  override_during = plan
  values = {
    arn = "arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-data"
  }
}
variables {
  name_prefix = "graveyard-dev"
  env         = "dev"
  account_id  = "123456789012"
  contact     = "ops@example.org"
}
run "the_table_is_a_single_on_demand_table_with_ttl_pitr_and_the_cmk" {
  command = plan
  assert {
    condition     = aws_dynamodb_table.data.name == "graveyard-dev-data" && aws_dynamodb_table.data.billing_mode == "PAY_PER_REQUEST"
    error_message = "On-demand table graveyard-<env>-data."
  }
  assert {
    condition     = aws_dynamodb_table.data.hash_key == "pk" && aws_dynamodb_table.data.range_key == "sk"
    error_message = "pk and sk."
  }
  assert {
    condition     = one([for t in aws_dynamodb_table.data.ttl : t.attribute_name]) == "ttl" && one([for t in aws_dynamodb_table.data.ttl : t.enabled])
    error_message = "TTL on the ttl attribute."
  }
  assert {
    condition     = one([for p in aws_dynamodb_table.data.point_in_time_recovery : p.enabled]) && aws_dynamodb_table.data.deletion_protection_enabled
    error_message = "PITR and deletion protection."
  }
  assert {
    condition     = one([for s in aws_dynamodb_table.data.server_side_encryption : s.enabled])
    error_message = "SSE with the CMK."
  }
  assert {
    condition     = [for g in aws_dynamodb_table.data.global_secondary_index : g.name] == ["gsi1"]
    error_message = "One GSI, gsi1 (SB-DATA-1)."
  }
}
run "the_key_rotates_has_an_alias_and_names_this_envs_roles_only" {
  command = plan
  assert {
    condition     = aws_kms_key.app.enable_key_rotation && aws_kms_alias.app.name == "alias/graveyard-dev-app"
    error_message = "Rotation on and the alias."
  }
  assert {
    condition     = [for s in jsondecode(aws_kms_key.app.policy).Statement : s.Sid] == ["AccountRoot", "WorkloadRolesOfThisEnv"]
    error_message = "The account root and the workload roles, nothing else."
  }
  assert {
    condition     = jsondecode(aws_kms_key.app.policy).Statement[1].Condition.ArnLike["aws:PrincipalArn"] == "arn:aws:iam::123456789012:role/graveyard-dev/graveyard-dev-*"
    error_message = "The workload statement must be limited to this env's role path and names."
  }
  assert {
    condition     = toset(jsondecode(aws_kms_key.app.policy).Statement[1].Action) == toset(["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"])
    error_message = "Roles may only use the key, not manage it."
  }
}
run "the_bucket_is_private_versioned_kms_encrypted_and_tls_only" {
  command = plan
  assert {
    condition     = aws_s3_bucket.artefacts.bucket_prefix == "graveyard-dev-artefacts-"
    error_message = "The bucket name starts with graveyard-<env>-."
  }
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.artefacts.block_public_acls,
      aws_s3_bucket_public_access_block.artefacts.block_public_policy,
      aws_s3_bucket_public_access_block.artefacts.ignore_public_acls,
      aws_s3_bucket_public_access_block.artefacts.restrict_public_buckets,
    ])
    error_message = "All four Block Public Access settings."
  }
  assert {
    condition     = aws_s3_bucket_versioning.artefacts.versioning_configuration[0].status == "Enabled"
    error_message = "Versioning on."
  }
  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.artefacts.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms" && one(aws_s3_bucket_server_side_encryption_configuration.artefacts.rule).bucket_key_enabled
    error_message = "SSE-KMS with the bucket key."
  }
  assert {
    condition     = one(aws_s3_bucket_ownership_controls.artefacts.rule).object_ownership == "BucketOwnerEnforced"
    error_message = "BucketOwnerEnforced."
  }
  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.artefacts.policy).Statement : s.Sid] == ["DenyInsecureTransport", "DenyPutWithOtherEncryption", "DenyPutWithNoEncryptionHeader"]
    error_message = "TLS-only and KMS-only writes."
  }
}
run "lifecycle_expires_scans_and_uploads_in_7_days_and_reports_in_30" {
  command = plan
  assert {
    condition     = { for r in aws_s3_bucket_lifecycle_configuration.artefacts.rule : r.id => one(r.expiration).days if length(r.expiration) > 0 } == { "scans-7-days" = 7, "uploads-7-days" = 7, "reports-30-days" = 30 }
    error_message = "scans/ and uploads/ 7 days, reports/ 30 days (SB-DATA-4)."
  }
  assert {
    condition     = [for r in aws_s3_bucket_lifecycle_configuration.artefacts.rule : one(r.noncurrent_version_expiration).noncurrent_days if length(r.noncurrent_version_expiration) > 0] == [1]
    error_message = "Noncurrent versions expire after 1 day."
  }
  assert {
    condition     = [for r in aws_s3_bucket_lifecycle_configuration.artefacts.rule : one(r.abort_incomplete_multipart_upload).days_after_initiation if length(r.abort_incomplete_multipart_upload) > 0] == [7]
    error_message = "Incomplete multipart uploads abort after 7 days."
  }
}
run "the_parameters_are_under_the_env_path_with_the_default_limits" {
  command = plan
  assert {
    condition = { for k, p in aws_ssm_parameter.config : p.name => p.value } == {
      "/graveyard/dev/limits/max-services"       = "50"
      "/graveyard/dev/limits/max-manifest-bytes" = "10485760"
      "/graveyard/dev/limits/max-file-bytes"     = "5242880"
      "/graveyard/dev/limits/max-purls"          = "2000"
      "/graveyard/dev/sources/contact"           = "ops@example.org"
    }
    error_message = "The limits and the contact are SSM parameters (SB-CFG-1)."
  }
  assert {
    condition     = aws_ssm_parameter.kill_switch.name == "/graveyard/dev/kill-switch" && aws_ssm_parameter.kill_switch.value == "false"
    error_message = "The kill switch starts false."
  }
  assert {
    condition     = output.ssm_parameter_arn_pattern == "arn:aws:ssm:eu-west-2:123456789012:parameter/graveyard/dev/*"
    error_message = "The read pattern covers the env's parameters only."
  }
}
run "prod_names_follow_the_prefix" {
  command = plan
  variables {
    name_prefix = "graveyard-prod"
    env         = "prod"
  }
  assert {
    condition     = aws_dynamodb_table.data.name == "graveyard-prod-data" && aws_s3_bucket.artefacts.bucket_prefix == "graveyard-prod-artefacts-"
    error_message = "Names follow the prefix."
  }
}
run "a_prefix_of_another_project_is_rejected" {
  command = plan
  variables {
    name_prefix = "other-dev"
  }
  expect_failures = [var.name_prefix]
}
