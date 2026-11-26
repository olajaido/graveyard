output "web_acl_arn" {
  description = "ARN of the Edge ACL, for the web_acl_id of both distributions."
  value       = aws_wafv2_web_acl.this.arn
}
output "web_acl_name" {
  description = "Name of the Edge ACL (<prefix>-edge)."
  value       = aws_wafv2_web_acl.this.name
}
