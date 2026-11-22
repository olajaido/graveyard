output "api_url" {
  description = "Execute endpoint of the HTTP API. The default stage has no path prefix."
  value       = aws_apigatewayv2_api.http.api_endpoint
}
output "api_id" {
  description = "ID of the HTTP API."
  value       = aws_apigatewayv2_api.http.id
}
output "function_name" {
  description = "Name of the api function."
  value       = module.fn.function_name
}
output "access_log_group_name" {
  description = "Name of the access log group, or null when access logging is off."
  value       = one(aws_cloudwatch_log_group.access[*].name)
}
