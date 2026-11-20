# Offline plan of the whole dev root with a mock provider: the module calls fit together (scan-backend, SB-INF-1, SB-INF-2).
mock_provider "aws" {}
override_resource {
  target          = module.data.aws_kms_key.app
  override_during = plan
  values = {
    arn    = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
    key_id = "00000000-0000-0000-0000-000000000000"
  }
}
override_resource {
  target          = module.data.aws_s3_bucket.artefacts
  override_during = plan
  values = {
    arn = "arn:aws:s3:::graveyard-dev-artefacts-20260101"
    id  = "graveyard-dev-artefacts-20260101"
  }
}
override_resource {
  target          = module.data.aws_dynamodb_table.data
  override_during = plan
  values = {
    arn = "arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-data"
  }
}
override_resource {
  target          = module.github_app.aws_secretsmanager_secret.reader
  override_during = plan
  values = {
    arn = "arn:aws:secretsmanager:eu-west-2:123456789012:secret:graveyard/dev/github/reader-AbCdEf"
  }
}
override_resource {
  target          = module.api.aws_apigatewayv2_api.http
  override_during = plan
  values = {
    id            = "abc123"
    execution_arn = "arn:aws:execute-api:eu-west-2:123456789012:abc123"
    api_endpoint  = "https://abc123.execute-api.eu-west-2.amazonaws.com"
  }
}
override_resource {
  target          = module.api.aws_cloudwatch_log_group.access
  override_during = plan
  values = {
    arn = "arn:aws:logs:eu-west-2:123456789012:log-group:/aws/vendedlogs/states/graveyard-dev-api-access"
  }
}
override_resource {
  target          = module.observability.aws_sns_topic.alerts
  override_during = plan
  values          = { arn = "arn:aws:sns:eu-west-2:123456789012:graveyard-dev-alerts" }
}
variables {
  allowed_account_ids = ["123456789012"]
  lambda_zip_path     = "../../modules/lambda-function/tests/fixtures/lambda.zip"
  lambda_zip_sha256   = "9940df3df16c98c88fcc166e2fe9bd3fb6c2dc3c4e7b36254445ea3cae987a5d"
  syft_layer_zip_path = "../../modules/lambda-function/tests/fixtures/lambda.zip"
  syft_layer_sha256   = "9940df3df16c98c88fcc166e2fe9bd3fb6c2dc3c4e7b36254445ea3cae987a5d"
}
run "the_root_wires_the_modules_with_the_env_prefix" {
  command = plan
  assert {
    condition     = output.name_prefix == "graveyard-dev" && output.table_name == "graveyard-dev-data" && output.state_machine_name == "graveyard-dev-scan"
    error_message = "Every name starts with graveyard-<env>-."
  }
  assert {
    condition     = output.reader_secret_name == "graveyard/dev/github/reader"
    error_message = "The reader secret path."
  }
  assert {
    condition     = module.workflow.state_machine_alias_arn == "arn:aws:states:eu-west-2:123456789012:stateMachine:graveyard-dev-scan:live"
    error_message = "The API starts the live alias of the scan state machine."
  }
}
run "every_role_carries_the_env_boundary_and_the_workload_path" {
  command = plan
  assert {
    condition     = module.api.function_name == "graveyard-dev-api" && length(module.workflow.function_names) == 7
    error_message = "One api function and seven task functions."
  }
  assert {
    condition     = module.workflow.sfn_role_boundary_arn == "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary"
    error_message = "The boundary ARN is built from the allowed account and the env prefix."
  }
}
run "the_total_reserved_concurrency_is_about_fifty" {
  command = plan
  assert {
    condition     = sum([for k, f in module.workflow.function_settings : f.reserved_concurrency]) + 8 == 50
    error_message = "42 for the task functions plus 8 for the api: about 50 per env (the review of 19 Nov 2026)."
  }
}
