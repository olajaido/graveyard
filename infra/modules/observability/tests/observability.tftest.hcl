# Offline tests for the observability module (SB-OBS-1).
mock_provider "aws" {}
override_resource {
  target          = aws_sns_topic.alerts
  override_during = plan
  values          = { arn = "arn:aws:sns:eu-west-2:123456789012:graveyard-dev-alerts" }
}
variables {
  name_prefix        = "graveyard-dev"
  env                = "dev"
  account_id         = "123456789012"
  function_names     = ["graveyard-dev-fetch", "graveyard-dev-api"]
  api_function_name  = "graveyard-dev-api"
  state_machine_name = "graveyard-dev-scan"
  api_id             = "abc123"
  table_name         = "graveyard-dev-data"
}
run "every_alarm_notifies_the_topic_and_is_named_with_the_prefix" {
  command = plan
  assert {
    condition = alltrue(concat(
      [for a in aws_cloudwatch_metric_alarm.lambda_errors : one(a.alarm_actions) == "arn:aws:sns:eu-west-2:123456789012:graveyard-dev-alerts" && startswith(a.alarm_name, "graveyard-dev-")],
      [for a in aws_cloudwatch_metric_alarm.lambda_throttles : one(a.alarm_actions) == "arn:aws:sns:eu-west-2:123456789012:graveyard-dev-alerts" && startswith(a.alarm_name, "graveyard-dev-")],
      [for a in [aws_cloudwatch_metric_alarm.scan_failed, aws_cloudwatch_metric_alarm.api_5xx, aws_cloudwatch_metric_alarm.dynamodb_throttles, aws_cloudwatch_metric_alarm.kill_switch] : one(a.alarm_actions) == "arn:aws:sns:eu-west-2:123456789012:graveyard-dev-alerts" && startswith(a.alarm_name, "graveyard-dev-")],
    ))
    error_message = "Every alarm goes to the topic (PRD section 12.1) and starts with graveyard-<env>-."
  }
  assert {
    condition     = aws_sns_topic.alerts.name == "graveyard-dev-alerts"
    error_message = "graveyard-<env>-alerts."
  }
}
run "lambda_alarms_use_the_thresholds_of_the_requirement" {
  command = plan
  assert {
    condition     = aws_cloudwatch_metric_alarm.lambda_errors["graveyard-dev-fetch"].threshold == 5 && aws_cloudwatch_metric_alarm.lambda_errors["graveyard-dev-fetch"].period == 300 && aws_cloudwatch_metric_alarm.lambda_errors["graveyard-dev-fetch"].comparison_operator == "GreaterThanThreshold"
    error_message = "Errors greater than 5 in 5 minutes."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.lambda_throttles["graveyard-dev-api"].threshold == 0 && aws_cloudwatch_metric_alarm.lambda_throttles["graveyard-dev-api"].metric_name == "Throttles"
    error_message = "Any throttle."
  }
  assert {
    condition     = toset(keys(aws_cloudwatch_metric_alarm.lambda_errors)) == toset(var.function_names) && toset(keys(aws_cloudwatch_metric_alarm.lambda_throttles)) == toset(var.function_names)
    error_message = "One errors alarm and one throttles alarm per function."
  }
}
run "the_state_machine_alarm_is_more_than_two_failures_in_fifteen_minutes" {
  command = plan
  assert {
    condition     = aws_cloudwatch_metric_alarm.scan_failed.metric_name == "ExecutionsFailed" && aws_cloudwatch_metric_alarm.scan_failed.threshold == 2 && aws_cloudwatch_metric_alarm.scan_failed.period == 900
    error_message = "ExecutionsFailed greater than 2 in 15 minutes."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.scan_failed.dimensions["StateMachineArn"] == "arn:aws:states:eu-west-2:123456789012:stateMachine:graveyard-dev-scan"
    error_message = "The dimension is the state machine ARN."
  }
}
run "the_api_and_table_alarms_use_metric_math" {
  command = plan
  assert {
    condition     = aws_cloudwatch_metric_alarm.api_5xx.threshold == 2 && [for q in aws_cloudwatch_metric_alarm.api_5xx.metric_query : q.id if try(q.return_data, false) == true] == ["rate"]
    error_message = "A 5xx rate above 2 percent."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.dynamodb_throttles.threshold == 0 && [for q in aws_cloudwatch_metric_alarm.dynamodb_throttles.metric_query : q.id if try(q.return_data, false) == true] == ["throttled"]
    error_message = "Any throttle on the table."
  }
}
run "the_kill_switch_has_a_metric_filter_on_the_api_log_group_and_an_alarm" {
  command = plan
  assert {
    condition     = aws_cloudwatch_log_metric_filter.kill_switch.log_group_name == "/aws/lambda/graveyard-dev-api" && aws_cloudwatch_log_metric_filter.kill_switch.pattern == "{ $.killSwitch = true }"
    error_message = "A filter on killSwitch = true in the api log group."
  }
  assert {
    condition     = one(aws_cloudwatch_log_metric_filter.kill_switch.metric_transformation).namespace == "Graveyard/dev"
    error_message = "The metric goes to Graveyard/<env>."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.kill_switch.namespace == "Graveyard/dev" && aws_cloudwatch_metric_alarm.kill_switch.threshold == 1 && aws_cloudwatch_metric_alarm.kill_switch.comparison_operator == "GreaterThanOrEqualToThreshold"
    error_message = "At least one refusal in 5 minutes."
  }
}
run "a_prefix_of_another_project_is_rejected" {
  command = plan
  variables {
    name_prefix = "other-dev"
  }
  expect_failures = [var.name_prefix]
}
