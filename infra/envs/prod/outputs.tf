output "name_prefix" {
  description = "Prefix of every named resource in this root (INF-NAME-1)."
  value       = local.name_prefix
}
output "api_url" {
  description = "Execute endpoint of the HTTP API. POST /v1/scans starts a scan (spec scan-backend)."
  value       = module.api.api_url
}
output "table_name" {
  description = "Name of the DynamoDB single table."
  value       = module.data.table_name
}
output "bucket_name" {
  description = "Name of the artefacts bucket."
  value       = module.data.bucket_name
}
output "state_machine_name" {
  description = "Name of the scan state machine."
  value       = module.workflow.state_machine_name
}
output "reader_secret_name" {
  description = "Name of the Reader app secret: an empty container until the key is set by hand (SB-MAN-1)."
  value       = module.github_app.secret_name
}
output "alerts_topic_arn" {
  description = "ARN of the alerts topic. No subscription yet."
  value       = module.observability.topic_arn
}
