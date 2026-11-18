# All policies are jsonencode() values in locals (INF-POL-1). ARNs are built from names, the
# partition and the account ID input. The one exception is the KMS key ARN: a key has no name-based
# ARN, so it comes from the resource (tests override it with override_resource).
locals {
  bucket_name = "${var.bucket_name_prefix}-${random_id.suffix.hex}"
  bucket_arn  = "arn:${var.partition}:s3:::${local.bucket_name}"
  key_arn     = aws_kms_key.state.arn

  ci_principals = concat(
    [var.ci_role_arns.plan],
    [for env in sort(keys(var.ci_role_arns.apply)) : var.ci_role_arns.apply[env]],
  )

  bucket_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        # A missing header also matches StringNotEquals, so this denies a write with no SSE-KMS header.
        # The S3 backend sends the header for state and lock files (design section 2).
        Sid       = "DenyWrongEncryption"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${local.bucket_arn}/*"
        Condition = { StringNotEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" } }
      },
      {
        Sid       = "DenyWrongKey"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${local.bucket_arn}/*"
        Condition = { StringNotEqualsIfExists = { "s3:x-amz-server-side-encryption-aws-kms-key-id" = local.key_arn } }
      },
    ]
  })

  key_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Standard account-root statement: IAM administrators keep control of the key and it cannot be locked out.
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:${var.partition}:iam::${var.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CiUseViaS3"
        Effect    = "Allow"
        Principal = { AWS = local.ci_principals }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource  = "*"
        Condition = { StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" } }
      },
    ]
  })
}
