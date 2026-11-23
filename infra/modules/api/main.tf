# The HTTP API and its Lambda (SB-API-1 to SB-API-10, SB-INF-7). Four routes, one AWS_PROXY integration with the live
# alias, throttling per route. Access logs (JSON, no query strings, bodies or headers) are off by default.
locals {
  function_name = "${var.name_prefix}-api"
  access_log    = "/aws/vendedlogs/states/${var.name_prefix}-api-access"
  statements = [
    { Sid = "Table", Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"], Resource = [var.table_arn, var.table_index_arn] },
    { Sid = "StartScans", Effect = "Allow", Action = ["states:StartExecution"], Resource = [var.state_machine_alias_arn, var.state_machine_arn] },
    { Sid = "Parameters", Effect = "Allow", Action = ["ssm:GetParameter", "ssm:GetParameters"], Resource = [var.ssm_parameter_arn_pattern] },
    { Sid = "Key", Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = [var.kms_key_arn] },
  ]
}
module "fn" {
  source = "../lambda-function"

  name                 = local.function_name
  env                  = var.env
  account_id           = var.account_id
  partition            = var.partition
  region               = var.region
  boundary_arn         = var.boundary_arn
  handler              = "api.handler.handler"
  filename             = var.lambda_zip_path
  zip_sha256           = var.lambda_zip_sha256
  memory_size          = var.memory_size
  timeout              = var.timeout
  reserved_concurrency = var.reserved_concurrency
  environment = {
    GRAVEYARD_ENV                = var.env
    TABLE_NAME                   = var.table_name
    STATE_MACHINE_ARN            = var.state_machine_alias_arn
    POWERTOOLS_SERVICE_NAME      = "graveyard"
    POWERTOOLS_METRICS_NAMESPACE = "Graveyard/${var.env}"
    LOG_LEVEL                    = "INFO"
  }
  statements         = local.statements
  log_retention_days = var.log_retention_days
}
resource "aws_apigatewayv2_api" "http" {
  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"
  description   = "Graveyard scan API (spec scan-backend)"
  dynamic "cors_configuration" {
    for_each = length(var.cors_allowed_origins) > 0 ? [1] : []
    content {
      allow_origins = var.cors_allowed_origins
      allow_methods = ["GET", "POST", "OPTIONS"]
      allow_headers = ["content-type"]
      max_age       = 600
    }
  }
}
resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = module.fn.alias_invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 15000
}
resource "aws_apigatewayv2_route" "route" {
  for_each  = toset(var.routes)
  api_id    = aws_apigatewayv2_api.http.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
  # checkov:skip=CKV_AWS_309:Scans of public repositories are readable by anyone with the link by design (SB-API-10).
}
resource "aws_cloudwatch_log_group" "access" {
  count             = var.access_logs_enabled ? 1 : 0
  name              = local.access_log
  retention_in_days = var.log_retention_days
  # The name sits under the vended-logs path the apply role may create. Creating the stage with access logging also needs
  # logs:PutResourcePolicy, which CI does not have, so the stage has no access logs until the security review (H11).
  # checkov:skip=CKV_AWS_158:Access logs hold no query string, body or header (SB-API-9); a CMK needs a key policy for the logs service.
  # checkov:skip=CKV_AWS_338:Retention is a variable; the default of 30 days is intended.
}
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = var.default_burst_limit
    throttling_rate_limit  = var.default_rate_limit
  }
  route_settings {
    route_key              = var.post_route_key
    throttling_burst_limit = var.post_burst_limit
    throttling_rate_limit  = var.post_rate_limit
  }
  # Access logging is off by default (variable access_logs_enabled, decision of 20 Nov 2026). The block is written only when on.
  dynamic "access_log_settings" {
    for_each = var.access_logs_enabled ? [1] : []
    content {
      destination_arn = aws_cloudwatch_log_group.access[0].arn
      format = jsonencode({
        requestId    = "$context.requestId"
        routeKey     = "$context.routeKey"
        status       = "$context.status"
        latencyMs    = "$context.responseLatency"
        integration  = "$context.integrationErrorMessage"
        requestTime  = "$context.requestTime"
        protocol     = "$context.protocol"
        responseSize = "$context.responseLength"
      })
    }
  }
  depends_on = [aws_apigatewayv2_route.route]
}
resource "aws_lambda_permission" "http_api" {
  statement_id  = "AllowHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = module.fn.function_name
  qualifier     = "live"
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
