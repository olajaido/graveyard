output "bucket_name" {
  description = "Name of the site bucket (graveyard-<env>-site-<random>). The deploy workflow syncs the build into it."
  value       = aws_s3_bucket.site.id
}
output "bucket_arn" {
  description = "ARN of the site bucket."
  value       = aws_s3_bucket.site.arn
}
output "distribution_id" {
  description = "ID of the site distribution. The deploy workflow invalidates it and edge-alarms watches it."
  value       = aws_cloudfront_distribution.site.id
}
output "distribution_arn" {
  description = "ARN of the site distribution."
  value       = aws_cloudfront_distribution.site.arn
}
output "distribution_domain_name" {
  description = "The d<id>.cloudfront.net name of the site distribution."
  value       = aws_cloudfront_distribution.site.domain_name
}
output "site_url" {
  description = "Public URL of the site."
  value       = "https://${var.site_host}"
}
output "csp" {
  description = "The Content-Security-Policy that the headers function sets. For the root test."
  value       = local.csp
}
output "web_acl_id" {
  description = "The web ACL ARN the distribution carries, or null. For the env root tests."
  value       = aws_cloudfront_distribution.site.web_acl_id
}
