output "bucket_name" {
  description = "Name of the state bucket (graveyard-tfstate-<random suffix>). Not a secret."
  value       = aws_s3_bucket.state.bucket
}

output "bucket_arn" {
  description = "ARN of the state bucket."
  value       = aws_s3_bucket.state.arn
}

output "kms_key_arn" {
  description = "ARN of the state KMS key."
  value       = aws_kms_key.state.arn
}

output "kms_key_id" {
  description = "ID (UUID) of the state KMS key."
  value       = aws_kms_key.state.key_id
}
