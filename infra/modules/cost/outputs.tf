output "budget_name" {
  description = "Name of the Graveyard monthly budget."
  value       = aws_budgets_budget.monthly.name
}

output "anomaly_monitor_arn" {
  description = "ARN of the custom anomaly monitor that this module created."
  value       = aws_ce_anomaly_monitor.project.arn
}

output "anomaly_subscription_arn" {
  description = "ARN of the anomaly email subscription."
  value       = aws_ce_anomaly_subscription.email.arn
}
