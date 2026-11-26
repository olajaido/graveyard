# Offline tests for edge-alarms (EDGE-OBS-1, EDGE-OBS-2). The root passes the us-east-1 provider as the default one; here it is mocked.
mock_provider "aws" {}
override_resource {
  target          = aws_sns_topic.edge
  override_during = plan
  values          = { arn = "arn:aws:sns:us-east-1:123456789012:graveyard-prod-edge-alerts" }
}
variables {
  name_prefix          = "graveyard-prod"
  site_distribution_id = "E2EXAMPLE12345"
  api_distribution_id  = "E4EXAMPLE67890"
}
run "the_topic_and_the_alarms_are_named_with_the_prefix_and_notify_the_topic" {
  command = plan
  assert {
    condition     = aws_sns_topic.edge.name == "graveyard-prod-edge-alerts"
    error_message = "graveyard-<env>-edge-alerts."
  }
  assert {
    condition     = toset(output.alarm_names) == toset(["graveyard-prod-cdn-site-5xx", "graveyard-prod-cdn-api-5xx"])
    error_message = "One alarm per distribution, named graveyard-<env>-cdn-<site|api>-5xx."
  }
  assert {
    condition     = alltrue([for k, a in aws_cloudwatch_metric_alarm.cdn_5xx : a.alarm_actions == toset(["arn:aws:sns:us-east-1:123456789012:graveyard-prod-edge-alerts"])])
    error_message = "Every alarm notifies the edge topic and nothing else."
  }
}
run "each_alarm_is_the_5xx_rate_above_2_percent_with_a_10_request_floor" {
  command = plan
  assert {
    condition = alltrue([
      for k, a in aws_cloudwatch_metric_alarm.cdn_5xx : (
        a.threshold == 2 && a.comparison_operator == "GreaterThanThreshold" && a.evaluation_periods == 1 && a.treat_missing_data == "notBreaching"
      )
    ])
    error_message = "Above 2 percent, one 5-minute period, missing data does not breach."
  }
  assert {
    condition = alltrue([
      for k, a in aws_cloudwatch_metric_alarm.cdn_5xx :
      one([for q in a.metric_query : q.expression if q.id == "rate"]) == "IF(requests >= 10, errors, 0)" && one([for q in a.metric_query : q.return_data if q.id == "rate"])
    ])
    error_message = "The value is the error rate only when there were at least 10 requests."
  }
}
run "the_metrics_are_the_cloudfront_defaults_of_the_right_distribution" {
  command = plan
  assert {
    condition = (
      one([for q in aws_cloudwatch_metric_alarm.cdn_5xx["site"].metric_query : one(q.metric).metric_name if q.id == "errors"]) == "5xxErrorRate" &&
      one([for q in aws_cloudwatch_metric_alarm.cdn_5xx["site"].metric_query : one(q.metric).stat if q.id == "errors"]) == "Average" &&
      one([for q in aws_cloudwatch_metric_alarm.cdn_5xx["site"].metric_query : one(q.metric).metric_name if q.id == "requests"]) == "Requests" &&
      one([for q in aws_cloudwatch_metric_alarm.cdn_5xx["site"].metric_query : one(q.metric).stat if q.id == "requests"]) == "Sum"
    )
    error_message = "5xxErrorRate (average) and Requests (sum), both default CloudFront metrics."
  }
  assert {
    condition = alltrue(flatten([
      for k, a in aws_cloudwatch_metric_alarm.cdn_5xx : [
        for q in a.metric_query : one(q.metric).namespace == "AWS/CloudFront" && one(q.metric).period == 300 && one(q.metric).dimensions["DistributionId"] == (k == "site" ? "E2EXAMPLE12345" : "E4EXAMPLE67890") && one(q.metric).dimensions["Region"] == "Global" && length(one(q.metric).dimensions) == 2
        if q.id != "rate"
      ]
    ]))
    error_message = "Namespace AWS/CloudFront, 5-minute periods, the distribution's ID and Region Global."
  }
}
run "threshold_and_floor_follow_the_variables" {
  command = plan
  variables {
    error_rate_threshold = 5
    min_requests         = 50
  }
  assert {
    condition     = alltrue([for k, a in aws_cloudwatch_metric_alarm.cdn_5xx : a.threshold == 5 && one([for q in a.metric_query : q.expression if q.id == "rate"]) == "IF(requests >= 50, errors, 0)"])
    error_message = "The threshold and the request floor come from the variables."
  }
}
run "a_bad_distribution_id_is_rejected" {
  command = plan
  variables {
    site_distribution_id = "not-an-id"
  }
  expect_failures = [var.site_distribution_id]
}
