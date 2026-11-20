# Offline tests for the lambda-function module (SB-INF-3, SB-INF-4). The zip file is a temp file written by
# the first run, so the precondition is exercised for real.
mock_provider "aws" {}
variables {
  name                 = "graveyard-dev-fetch"
  env                  = "dev"
  account_id           = "123456789012"
  boundary_arn         = "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary"
  handler              = "workflow.fetch.handler"
  filename             = "tests/fixtures/lambda.zip"
  zip_sha256           = "9940df3df16c98c88fcc166e2fe9bd3fb6c2dc3c4e7b36254445ea3cae987a5d"
  reserved_concurrency = 5
  environment          = { GRAVEYARD_ENV = "dev" }
  statements = [
    { Sid = "Table", Effect = "Allow", Action = ["dynamodb:UpdateItem"], Resource = ["arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-data"] },
  ]
}
run "the_function_is_python_arm64_traced_versioned_and_aliased" {
  command = plan
  assert {
    condition     = aws_lambda_function.this.runtime == "python3.12" && one(aws_lambda_function.this.architectures) == "arm64"
    error_message = "Python 3.12 on arm64."
  }
  assert {
    condition     = aws_lambda_function.this.publish == true && aws_lambda_function.this.tracing_config[0].mode == "Active"
    error_message = "publish = true and X-Ray Active."
  }
  assert {
    condition     = aws_lambda_alias.live.name == "live" && aws_lambda_function.this.reserved_concurrent_executions == 5
    error_message = "A live alias and the reserved concurrency."
  }
  assert {
    condition     = aws_lambda_function.this.function_name == "graveyard-dev-fetch" && aws_cloudwatch_log_group.this.name == "/aws/lambda/graveyard-dev-fetch"
    error_message = "Names start with graveyard-<env>- and the log group is /aws/lambda/<name>."
  }
}
run "the_role_is_on_the_workload_path_with_the_boundary" {
  command = plan
  assert {
    condition     = aws_iam_role.this.path == "/graveyard-dev/" && aws_iam_role.this.permissions_boundary == "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary"
    error_message = "The role needs the env path and the boundary (INF-APPLY-4)."
  }
  assert {
    condition     = jsondecode(aws_iam_role.this.assume_role_policy).Statement[0].Principal.Service == "lambda.amazonaws.com"
    error_message = "Only the Lambda service may assume the role."
  }
}
run "the_policy_is_logs_xray_and_the_given_statements_only" {
  command = plan
  assert {
    condition     = [for s in jsondecode(aws_iam_role_policy.this.policy).Statement : s.Sid] == ["Logs", "XRay", "Table"]
    error_message = "Base statements first, then the caller's."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.this.policy).Statement[0].Resource == ["arn:aws:logs:eu-west-2:123456789012:log-group:/aws/lambda/graveyard-dev-fetch:*"]
    error_message = "Logs only on the function's own log group."
  }
  assert {
    condition     = [for s in jsondecode(aws_iam_role_policy.this.policy).Statement : s.Sid if s.Resource == "*"] == ["XRay"]
    error_message = "Only X-Ray (E1, E2) may use *."
  }
}
run "environment_holds_what_the_caller_gave_and_nothing_else" {
  command = plan
  assert {
    condition     = length(aws_lambda_function.this.environment[0].variables) == 1 && aws_lambda_function.this.environment[0].variables["GRAVEYARD_ENV"] == "dev"
    error_message = "No variables added by the module."
  }
}
run "a_name_outside_the_prefix_is_rejected" {
  command = plan
  variables {
    name = "someone-elses-function"
  }
  expect_failures = [var.name]
}
run "a_boundary_of_another_kind_is_rejected" {
  command = plan
  variables {
    boundary_arn = "arn:aws:iam::123456789012:policy/other"
  }
  expect_failures = [var.boundary_arn]
}
run "a_bad_hash_is_rejected" {
  command = plan
  variables {
    zip_sha256 = "abc"
  }
  expect_failures = [var.zip_sha256]
}
run "a_zip_that_differs_from_the_planned_hash_stops_the_apply" {
  command = plan
  variables {
    zip_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
  }
  expect_failures = [aws_lambda_function.this]
}
