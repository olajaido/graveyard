output "function_name" {
  description = "Function name."
  value       = aws_lambda_function.this.function_name
}
output "function_arn" {
  description = "Unqualified function ARN."
  value       = aws_lambda_function.this.arn
}
output "alias_arn" {
  description = "ARN of the live alias. The API and the state machine invoke this, never $LATEST (terraform.md)."
  value       = aws_lambda_alias.live.arn
}
output "alias_invoke_arn" {
  description = "Invoke ARN of the live alias, for API Gateway."
  value       = aws_lambda_alias.live.invoke_arn
}
output "role_arn" {
  description = "ARN of the function's role."
  value       = aws_iam_role.this.arn
}
output "log_group_name" {
  description = "Name of the function's log group."
  value       = aws_cloudwatch_log_group.this.name
}
output "role_policy_json" {
  description = "The inline policy document of the role (for tests and review)."
  value       = aws_iam_role_policy.this.policy
}
output "environment" {
  description = "The environment variables of the function: names only."
  value       = var.environment
}
