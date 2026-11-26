# The two CloudFront 5xx alarms of one env and the topic they notify (spec infra-edge, EDGE-OBS-1 and EDGE-OBS-2). CloudFront
# publishes its metrics in us-east-1 only, and an alarm can notify only a topic in its own region, so the root passes the
# us-east-1 provider as this module's default provider and the topic is made here. There is no subscription in Terraform: the
# maintainer subscribes by hand, as for the eu-west-2 topic.
locals {
  distributions = {
    site = var.site_distribution_id
    api  = var.api_distribution_id
  }
}
resource "aws_sns_topic" "edge" {
  # checkov:skip=CKV_AWS_26:CloudWatch alarms cannot publish to a topic encrypted with the AWS managed key, and a CMK needs a key policy for the alarms service; the messages hold alarm names only.
  name = "${var.name_prefix}-edge-alerts"
}
resource "aws_cloudwatch_metric_alarm" "cdn_5xx" {
  for_each            = local.distributions
  alarm_name          = "${var.name_prefix}-cdn-${each.key}-5xx"
  alarm_description   = "More than ${var.error_rate_threshold} percent of ${each.key} distribution requests ended in a 5xx in 5 minutes, with at least ${var.min_requests} requests."
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.error_rate_threshold
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.edge.arn]
  metric_query {
    id          = "rate"
    expression  = "IF(requests >= ${var.min_requests}, errors, 0)"
    label       = "5xx error rate (percent)"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/CloudFront"
      metric_name = "5xxErrorRate"
      dimensions  = { DistributionId = each.value, Region = "Global" }
      period      = 300
      stat        = "Average"
    }
  }
  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/CloudFront"
      metric_name = "Requests"
      dimensions  = { DistributionId = each.value, Region = "Global" }
      period      = 300
      stat        = "Sum"
    }
  }
}
