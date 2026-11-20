# The alerts topic and the alarms of SB-OBS-1. Every alarm notifies the topic; there is no subscription yet, the maintainer
# subscribes by hand (SB-OBS-1). Names start with graveyard-<env>- (INF-NAME-1).
locals {
  topic_name   = "${var.name_prefix}-alerts"
  machine_arn  = "arn:${var.partition}:states:${var.region}:${var.account_id}:stateMachine:${var.state_machine_name}"
  namespace    = "Graveyard/${var.env}"
  api_log      = "/aws/lambda/${var.api_function_name}"
  alarm_action = [aws_sns_topic.alerts.arn]
}
resource "aws_sns_topic" "alerts" {
  name = local.topic_name
  # checkov:skip=CKV_AWS_26:CloudWatch alarms cannot publish to a topic encrypted with the AWS managed key, and a CMK needs a key policy for the alarms service; the messages hold alarm names only.
}
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each            = toset(var.function_names)
  alarm_name          = "${each.value}-errors"
  alarm_description   = "More than 5 errors in 5 minutes (SB-OBS-1)."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_action
}
resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  for_each            = toset(var.function_names)
  alarm_name          = "${each.value}-throttles"
  alarm_description   = "Any throttle (SB-OBS-1)."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_action
}
resource "aws_cloudwatch_metric_alarm" "scan_failed" {
  alarm_name          = "${var.name_prefix}-scan-executions-failed"
  alarm_description   = "More than 2 failed scan executions in 15 minutes. Scans that fail because of their input end as a success of the workflow and do not count."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = local.machine_arn }
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 2
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_action
}
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.name_prefix}-api-5xx-rate"
  alarm_description   = "More than 2 percent of API requests ended in a 5xx in 5 minutes."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 2
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_action
  metric_query {
    id          = "rate"
    expression  = "IF(requests > 0, 100 * errors / requests, 0)"
    label       = "5xx rate (percent)"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "5xx"
      dimensions  = { ApiId = var.api_id }
      period      = 300
      stat        = "Sum"
    }
  }
  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "Count"
      dimensions  = { ApiId = var.api_id }
      period      = 300
      stat        = "Sum"
    }
  }
}
resource "aws_cloudwatch_metric_alarm" "dynamodb_throttles" {
  alarm_name          = "${var.name_prefix}-table-throttled-requests"
  alarm_description   = "Any read or write throttle on the table. ThrottledRequests needs an Operation dimension, so the table-level throttle events are summed."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_action
  metric_query {
    id          = "throttled"
    expression  = "reads + writes"
    label       = "Throttled requests"
    return_data = true
  }
  metric_query {
    id = "reads"
    metric {
      namespace   = "AWS/DynamoDB"
      metric_name = "ReadThrottleEvents"
      dimensions  = { TableName = var.table_name }
      period      = 300
      stat        = "Sum"
    }
  }
  metric_query {
    id = "writes"
    metric {
      namespace   = "AWS/DynamoDB"
      metric_name = "WriteThrottleEvents"
      dimensions  = { TableName = var.table_name }
      period      = 300
      stat        = "Sum"
    }
  }
}
# The api function logs a structured field killSwitch=true each time the kill switch refuses a scan (SB-API-8, SB-OBS-1).
resource "aws_cloudwatch_log_metric_filter" "kill_switch" {
  name           = "${var.name_prefix}-kill-switch"
  log_group_name = local.api_log
  pattern        = "{ $.killSwitch = true }"
  metric_transformation {
    name      = "KillSwitchRefusals"
    namespace = local.namespace
    value     = "1"
  }
}
resource "aws_cloudwatch_metric_alarm" "kill_switch" {
  alarm_name          = "${var.name_prefix}-kill-switch-active"
  alarm_description   = "The kill switch refused a scan: cached-demo mode is on (notify immediately)."
  namespace           = local.namespace
  metric_name         = "KillSwitchRefusals"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_action
  depends_on          = [aws_cloudwatch_log_metric_filter.kill_switch]
}
