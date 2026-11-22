# Offline tests for the api module (SB-API-7, SB-API-9, SB-INF-5, SB-INF-7).
mock_provider "aws" {}
override_resource {
  target          = aws_apigatewayv2_api.http
  override_during = plan
  values = {
    id            = "abc123"
    execution_arn = "arn:aws:execute-api:eu-west-2:123456789012:abc123"
    api_endpoint  = "https://abc123.execute-api.eu-west-2.amazonaws.com"
  }
}
variables {
  name_prefix               = "graveyard-dev"
  env                       = "dev"
  account_id                = "123456789012"
  boundary_arn              = "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary"
  table_name                = "graveyard-dev-data"
  table_arn                 = "arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-data"
  table_index_arn           = "arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-data/index/gsi1"
  kms_key_arn               = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
  ssm_parameter_arn_pattern = "arn:aws:ssm:eu-west-2:123456789012:parameter/graveyard/dev/*"
  state_machine_arn         = "arn:aws:states:eu-west-2:123456789012:stateMachine:graveyard-dev-scan"
  state_machine_alias_arn   = "arn:aws:states:eu-west-2:123456789012:stateMachine:graveyard-dev-scan:live"
  lambda_zip_path           = "tests/fixtures/lambda.zip"
  lambda_zip_sha256         = "9940df3df16c98c88fcc166e2fe9bd3fb6c2dc3c4e7b36254445ea3cae987a5d"
}
run "the_api_has_exactly_the_four_routes_and_one_proxy_integration" {
  command = plan
  assert {
    condition     = toset([for r in aws_apigatewayv2_route.route : r.route_key]) == toset(["POST /v1/scans", "GET /v1/scans/{scanId}", "GET /v1/scans/{scanId}/graves", "GET /v1/scans/{scanId}/graves/{purl+}"])
    error_message = "Four routes (SB-API-7)."
  }
  assert {
    condition     = aws_apigatewayv2_integration.api.integration_type == "AWS_PROXY" && aws_apigatewayv2_integration.api.payload_format_version == "2.0"
    error_message = "AWS_PROXY with payload format 2.0."
  }
  assert {
    condition     = aws_apigatewayv2_api.http.name == "graveyard-dev-api" && aws_apigatewayv2_api.http.protocol_type == "HTTP"
    error_message = "An HTTP API named graveyard-<env>-api."
  }
}
run "the_post_route_is_throttled_harder_than_the_default" {
  command = plan
  assert {
    condition     = one(aws_apigatewayv2_stage.default.route_settings).route_key == "POST /v1/scans" && one(aws_apigatewayv2_stage.default.route_settings).throttling_rate_limit < one(aws_apigatewayv2_stage.default.default_route_settings).throttling_rate_limit
    error_message = "POST /v1/scans has a lower rate than the default (SB-API-9)."
  }
  assert {
    condition     = one(aws_apigatewayv2_stage.default.route_settings).throttling_burst_limit < one(aws_apigatewayv2_stage.default.default_route_settings).throttling_burst_limit
    error_message = "And a lower burst."
  }
  assert {
    condition     = aws_apigatewayv2_stage.default.name == "$default" && aws_apigatewayv2_stage.default.auto_deploy
    error_message = "The default stage deploys automatically."
  }
}
run "access_logs_hold_no_query_string_body_or_header" {
  command = plan
  variables {
    access_logs_enabled = true
  }
  assert {
    condition     = !anytrue([for v in values(jsondecode(one(aws_apigatewayv2_stage.default.access_log_settings).format)) : can(regex("request(Query|Body|Header)|queryString|authorization|headers|body", v))])
    error_message = "No query string, body or header in the access log (SB-API-9)."
  }
}
run "cors_is_off_by_default_and_never_star" {
  command = plan
  assert {
    condition     = length(aws_apigatewayv2_api.http.cors_configuration) == 0
    error_message = "No browser origin by default."
  }
}
run "cors_origins_are_listed_when_given" {
  command = plan
  variables {
    cors_allowed_origins = ["https://graveyard.example"]
  }
  assert {
    condition     = one(aws_apigatewayv2_api.http.cors_configuration).allow_origins == toset(["https://graveyard.example"])
    error_message = "The listed origin only."
  }
}
run "a_star_origin_is_rejected" {
  command = plan
  variables {
    cors_allowed_origins = ["*"]
  }
  expect_failures = [var.cors_allowed_origins]
}
run "the_function_may_read_write_the_table_start_scans_and_read_parameters" {
  command = plan
  assert {
    condition = jsonencode(sort(distinct(flatten([for s in jsondecode(module.fn.role_policy_json).Statement : s.Action])))) == jsonencode([
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:UpdateItem", "kms:Decrypt", "kms:GenerateDataKey",
      "logs:CreateLogStream", "logs:PutLogEvents", "ssm:GetParameter", "ssm:GetParameters", "states:StartExecution",
      "xray:PutTelemetryRecords", "xray:PutTraceSegments",
    ])
    error_message = "The api role is exactly SB-INF-5 (and UpdateItem for a failed start)."
  }
  assert {
    condition     = contains(flatten([for s in jsondecode(module.fn.role_policy_json).Statement : s.Resource if s.Sid == "StartScans"]), "arn:aws:states:eu-west-2:123456789012:stateMachine:graveyard-dev-scan:live")
    error_message = "StartExecution through the live alias."
  }
  assert {
    condition     = contains(flatten([for s in jsondecode(module.fn.role_policy_json).Statement : s.Resource if s.Sid == "Table"]), "arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-data/index/gsi1")
    error_message = "The table and the index."
  }
}
run "the_gateway_may_invoke_only_the_live_alias_of_the_api_function_from_this_api" {
  command = plan
  assert {
    condition     = aws_lambda_permission.http_api.qualifier == "live" && aws_lambda_permission.http_api.function_name == "graveyard-dev-api" && aws_lambda_permission.http_api.principal == "apigateway.amazonaws.com"
    error_message = "Only the live alias."
  }
  assert {
    condition     = aws_lambda_permission.http_api.source_arn == "arn:aws:execute-api:eu-west-2:123456789012:abc123/*/*"
    error_message = "Only from this API."
  }
  assert {
    condition     = module.fn.environment["STATE_MACHINE_ARN"] == "arn:aws:states:eu-west-2:123456789012:stateMachine:graveyard-dev-scan:live"
    error_message = "The function starts the alias."
  }
}
run "the_access_log_group_is_under_the_vended_logs_path_of_this_env" {
  command = plan
  variables {
    access_logs_enabled = true
  }
  assert {
    condition     = aws_cloudwatch_log_group.access[0].name == "/aws/vendedlogs/states/graveyard-dev-api-access"
    error_message = "The log group name must be one the apply role may create."
  }
}
run "access_logging_is_off_by_default_with_no_stage_setting_and_no_log_group" {
  command = plan
  assert {
    condition     = length(aws_apigatewayv2_stage.default.access_log_settings) == 0
    error_message = "By default the stage has no access log settings (decision of 20 Nov 2026, H11)."
  }
  assert {
    condition     = length(aws_cloudwatch_log_group.access) == 0 && output.access_log_group_name == null
    error_message = "By default no access log group exists and the output is null."
  }
}
run "access_logging_when_enabled_writes_the_stage_setting_and_the_group" {
  command = plan
  variables {
    access_logs_enabled = true
  }
  assert {
    condition     = length(aws_apigatewayv2_stage.default.access_log_settings) == 1
    error_message = "When enabled the stage has one access log setting."
  }
  assert {
    condition     = length(aws_cloudwatch_log_group.access) == 1 && output.access_log_group_name == "/aws/vendedlogs/states/graveyard-dev-api-access"
    error_message = "When enabled one access log group exists, under the vended-logs path."
  }
  assert {
    condition     = aws_cloudwatch_log_group.access[0].retention_in_days == 30
    error_message = "The group keeps the retention variable."
  }
}
run "throttling_and_default_route_settings_are_the_same_with_logging_off_or_on" {
  command = plan
  assert {
    condition     = one(aws_apigatewayv2_stage.default.default_route_settings).throttling_rate_limit == 50 && one(aws_apigatewayv2_stage.default.default_route_settings).throttling_burst_limit == 100
    error_message = "Default throttling is unchanged by the logging switch."
  }
  assert {
    condition     = one(aws_apigatewayv2_stage.default.route_settings).throttling_rate_limit == 2 && one(aws_apigatewayv2_stage.default.route_settings).throttling_burst_limit == 5
    error_message = "POST throttling is unchanged by the logging switch."
  }
}
