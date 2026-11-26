output "distribution_id" {
  description = "ID of the API distribution. edge-alarms watches it."
  value       = aws_cloudfront_distribution.api.id
}
output "distribution_arn" {
  description = "ARN of the API distribution."
  value       = aws_cloudfront_distribution.api.arn
}
output "distribution_domain_name" {
  description = "The d<id>.cloudfront.net name of the API distribution."
  value       = aws_cloudfront_distribution.api.domain_name
}
output "api_url" {
  description = "Public URL of the API. The web build gets it as NEXT_PUBLIC_API_URL."
  value       = "https://${var.api_host}"
}
output "web_acl_id" {
  description = "The web ACL ARN the distribution carries, or null. For the env root tests."
  value       = aws_cloudfront_distribution.api.web_acl_id
}
