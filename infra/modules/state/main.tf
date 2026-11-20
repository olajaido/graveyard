resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "state" {
  #checkov:skip=CKV_AWS_18:No access logging: a second bucket for one maintainer's state adds cost and noise. CloudTrail data events are the hardening path (PRD 10.3).
  #checkov:skip=CKV_AWS_144:No cross-region replication: Graveyard is single-region by design (eu-west-2, data residency) and versioning covers recovery.
  #checkov:skip=CKV2_AWS_62:No event notifications: nothing consumes events from the state bucket.
  bucket = local.bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = local.key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = local.bucket_policy

  # The public access block must exist first, or S3 rejects a policy change while it is being applied.
  depends_on = [aws_s3_bucket_public_access_block.state]
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "state-versions-envs"
    status = "Enabled"

    filter {
      prefix = "envs/"
    }

    noncurrent_version_expiration {
      noncurrent_days           = var.state_noncurrent_days
      newer_noncurrent_versions = var.state_noncurrent_keep
    }
  }

  rule {
    id     = "state-versions-bootstrap"
    status = "Enabled"

    filter {
      prefix = "bootstrap/"
    }

    noncurrent_version_expiration {
      noncurrent_days           = var.state_noncurrent_days
      newer_noncurrent_versions = var.state_noncurrent_keep
    }
  }

  # Saved plans (decision C5). Kept apart from housekeeping: S3 does not allow expired_object_delete_marker
  # and a current-version expiration in one rule.
  rule {
    id     = "plans"
    status = "Enabled"

    filter {
      prefix = "plans/"
    }

    expiration {
      days = var.plans_expiry_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  rule {
    id     = "housekeeping"
    status = "Enabled"

    filter {}

    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.state]
}
