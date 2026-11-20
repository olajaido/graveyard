output "secret_arn" {
  description = "ARN of the reader secret (an empty container until the key is set by hand)."
  value       = aws_secretsmanager_secret.reader.arn
}
output "secret_name" {
  description = "Name of the reader secret, graveyard/<env>/github/reader."
  value       = aws_secretsmanager_secret.reader.name
}
output "parameter_names" {
  description = "Names of the App ID and installation ID parameters."
  value       = [for p in aws_ssm_parameter.identifier : p.name]
}
