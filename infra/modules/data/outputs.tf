output "kms_key_arn" {
  description = "ARN of the app CMK."
  value       = aws_kms_key.app.arn
}
output "table_name" {
  description = "Name of the DynamoDB single table."
  value       = aws_dynamodb_table.data.name
}
output "table_arn" {
  description = "ARN of the table."
  value       = aws_dynamodb_table.data.arn
}
output "table_index_arn" {
  description = "ARN of GSI1."
  value       = "${aws_dynamodb_table.data.arn}/index/gsi1"
}
output "bucket_name" {
  description = "Name of the artefacts bucket."
  value       = aws_s3_bucket.artefacts.id
}
output "bucket_arn" {
  description = "ARN of the artefacts bucket."
  value       = aws_s3_bucket.artefacts.arn
}
output "ssm_parameter_arn_pattern" {
  description = "ARN pattern of the env's SSM parameters, for read policies."
  value       = "arn:${var.partition}:ssm:${var.region}:${var.account_id}:parameter/graveyard/${var.env}/*"
}
