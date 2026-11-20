output "oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider, built from account_id and partition. The provider is the shared account's existing one unless create_oidc_provider is true."
  value       = local.arn.oidc
}

output "plan_role_arn" {
  description = "ARN of the read-only plan role."
  value       = aws_iam_role.plan.arn
}

output "apply_role_arns" {
  description = "ARNs of the apply roles, by env."
  value       = { for e, r in aws_iam_role.apply : e => r.arn }
}

output "boundary_arns" {
  description = "ARNs of the workload permissions boundaries, by env. Every workload role of an env must carry its env's boundary."
  value       = local.boundary_arn
}

output "plan_role_name" {
  description = "Name of the plan role. Known at plan time, unlike the ARN."
  value       = aws_iam_role.plan.name
}

output "apply_role_names" {
  description = "Names of the apply roles, by env."
  value       = { for e, r in aws_iam_role.apply : e => r.name }
}
