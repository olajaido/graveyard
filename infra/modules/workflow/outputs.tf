output "state_machine_name" {
  description = "Name of the scan state machine."
  value       = local.machine_name
}
output "state_machine_arn" {
  description = "ARN of the scan state machine."
  value       = local.machine_arn
}
output "state_machine_alias_arn" {
  description = "ARN of the live alias. The API starts executions through it (terraform.md)."
  value       = local.alias_arn
}
output "function_names" {
  description = "Names of the seven task functions."
  value       = [for m in module.fn : m.function_name]
}
output "role_names" {
  description = "Names of the task roles and the state machine role."
  value       = concat([for m in module.fn : m.function_name], [aws_iam_role.sfn.name])
}
output "function_settings" {
  description = "Memory, timeout and reserved concurrency of the task functions."
  value       = var.functions
}
output "sfn_role_boundary_arn" {
  description = "The permissions boundary of the state machine role."
  value       = aws_iam_role.sfn.permissions_boundary
}
