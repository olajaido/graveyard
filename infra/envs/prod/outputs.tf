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
output "site_url" {
  description = "Public URL of the site."
  value       = module.edge_site.site_url
}
output "api_public_url" {
  description = "Public URL of the API (https://<API host>). The web build gets it as NEXT_PUBLIC_API_URL."
  value       = module.edge_api.api_url
}
output "site_bucket_name" {
  description = "Name of the site bucket. The deploy workflow syncs the web build into it."
  value       = module.edge_site.bucket_name
}
output "site_distribution_id" {
  description = "ID of the site distribution. The deploy workflow invalidates it."
  value       = module.edge_site.distribution_id
}
output "api_distribution_id" {
  description = "ID of the API distribution."
  value       = module.edge_api.distribution_id
}
output "web_acl_arn" {
  description = "ARN of the Edge ACL, or null when the env has none."
  value       = one(module.edge_waf[*].web_acl_arn)
}
output "edge_alerts_topic_arn" {
  description = "ARN of the edge alerts topic in us-east-1. No subscription yet; subscribe by hand (EDGE-MAN-4)."
  value       = module.edge_alarms.topic_arn
}
