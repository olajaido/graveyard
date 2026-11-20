# The data layer of the scan backend (SB-DATA-1, SB-DATA-4, SB-DATA-5, SB-CFG-1): the app CMK, the DynamoDB single table,
# the artefacts bucket and the SSM parameters. DynamoDB, the table, the key and the bucket cannot be destroyed by accident
# (prevent_destroy, terraform.md).
locals {
  table_name  = "${var.name_prefix}-data"
  ssm_prefix  = "/graveyard/${var.env}"
  role_arn_re = "arn:${var.partition}:iam::${var.account_id}:role/graveyard-${var.env}/${var.name_prefix}-*"
  key_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The standard statement: it lets IAM policies (the apply role, the maintainer) manage the key and keeps it from being locked out.
        Sid       = "AccountRoot"
        Effect    = "Allow"
        Principal = { AWS = "arn:${var.partition}:iam::${var.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # The workload roles of this env only. A principal ARN in a key policy must exist when the key is made, and the roles
        # are made after the key, so the roles are matched by path and name with a condition instead of by ARN.
        Sid       = "WorkloadRolesOfThisEnv"
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action    = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource  = "*"
        Condition = {
          StringEquals = { "aws:PrincipalAccount" = var.account_id }
          ArnLike      = { "aws:PrincipalArn" = local.role_arn_re }
        }
      },
    ]
  })
  bucket_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.artefacts.arn, "${aws_s3_bucket.artefacts.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "DenyPutWithOtherEncryption"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.artefacts.arn}/*"
        Condition = { StringNotEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" } }
      },
      {
        Sid       = "DenyPutWithNoEncryptionHeader"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.artefacts.arn}/*"
        Condition = { Null = { "s3:x-amz-server-side-encryption" = "true" } }
      },
    ]
  })
  parameters = {
    "limits/max-services"       = tostring(var.limits.max_services)
    "limits/max-manifest-bytes" = tostring(var.limits.max_manifest_bytes)
    "limits/max-file-bytes"     = tostring(var.limits.max_file_bytes)
    "limits/max-purls"          = tostring(var.limits.max_purls)
    "sources/contact"           = var.contact
  }
}
resource "aws_kms_key" "app" {
  description             = "${var.name_prefix} app key: table, artefacts and the reader secret"
  enable_key_rotation     = true
  deletion_window_in_days = var.key_deletion_window_days
  policy                  = local.key_policy
  lifecycle {
    prevent_destroy = true
  }
}
resource "aws_kms_alias" "app" {
  name          = "alias/${var.name_prefix}-app"
  target_key_id = aws_kms_key.app.key_id
}
resource "aws_dynamodb_table" "data" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  # hash_key and range_key are marked deprecated in provider 6.73, but key_schema blocks are not accepted by this version.
  hash_key  = "pk"
  range_key = "sk"
  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "gsi1pk"
    type = "S"
  }
  attribute {
    name = "gsi1sk"
    type = "S"
  }
  global_secondary_index {
    name            = "gsi1"
    hash_key        = "gsi1pk"
    range_key       = "gsi1sk"
    projection_type = "ALL"
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
  point_in_time_recovery {
    enabled = true
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.app.arn
  }
  deletion_protection_enabled = true
  lifecycle {
    prevent_destroy = true
  }
}
resource "aws_s3_bucket" "artefacts" {
  # A generated suffix makes the global name unique without writing the account ID into it.
  bucket_prefix = "${var.name_prefix}-artefacts-"
  lifecycle {
    prevent_destroy = true
  }
  # checkov:skip=CKV_AWS_144:No cross-region replication: scan artefacts are temporary (7 days).
  # checkov:skip=CKV2_AWS_62:No event notifications are needed.
  # checkov:skip=CKV_AWS_18:Access logging needs a log bucket the project does not have; CloudTrail data events are an account decision.
}
resource "aws_s3_bucket_versioning" "artefacts" {
  bucket = aws_s3_bucket.artefacts.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "artefacts" {
  bucket = aws_s3_bucket.artefacts.id
  rule {
    bucket_key_enabled = true
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.app.arn
    }
  }
}
resource "aws_s3_bucket_public_access_block" "artefacts" {
  bucket                  = aws_s3_bucket.artefacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "artefacts" {
  bucket = aws_s3_bucket.artefacts.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}
resource "aws_s3_bucket_policy" "artefacts" {
  bucket     = aws_s3_bucket.artefacts.id
  policy     = local.bucket_policy
  depends_on = [aws_s3_bucket_public_access_block.artefacts]
}
resource "aws_s3_bucket_lifecycle_configuration" "artefacts" {
  bucket = aws_s3_bucket.artefacts.id
  # scans/ holds manifests, SBOMs and graph files: expire after 7 days (security.md data retention).
  rule {
    id     = "scans-7-days"
    status = "Enabled"
    filter {
      prefix = "scans/"
    }
    expiration {
      days = 7
    }
  }
  rule {
    id     = "uploads-7-days"
    status = "Enabled"
    filter {
      prefix = "uploads/"
    }
    expiration {
      days = 7
    }
  }
  rule {
    id     = "reports-30-days"
    status = "Enabled"
    filter {
      prefix = "reports/"
    }
    expiration {
      days = 30
    }
  }
  rule {
    id     = "noncurrent-and-multipart"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
  depends_on = [aws_s3_bucket_versioning.artefacts]
}
resource "aws_ssm_parameter" "config" {
  for_each = local.parameters
  name     = "${local.ssm_prefix}/${each.key}"
  type     = "String"
  value    = each.value
  # checkov:skip=CKV2_AWS_34:Runtime config, not secrets (security.md: SSM holds config, Secrets Manager holds secrets).
}
resource "aws_ssm_parameter" "kill_switch" {
  name  = "${local.ssm_prefix}/kill-switch"
  type  = "String"
  value = "false"
  # checkov:skip=CKV2_AWS_34:A flag, not a secret (security.md).
  # The kill switch is flipped by hand in an emergency (SB-API-8); Terraform must not set it back to false.
  lifecycle {
    ignore_changes = [value]
  }
}
