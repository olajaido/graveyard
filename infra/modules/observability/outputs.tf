output "topic_arn" {
  description = "ARN of the alerts topic. Subscribe to it by hand."
  value       = aws_sns_topic.alerts.arn
}
output "alarm_names" {
  description = "Names of every alarm."
  value = concat(
    [for a in aws_cloudwatch_metric_alarm.lambda_errors : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.lambda_throttles : a.alarm_name],
    [
      aws_cloudwatch_metric_alarm.scan_failed.alarm_name,
      aws_cloudwatch_metric_alarm.api_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.dynamodb_throttles.alarm_name,
      aws_cloudwatch_metric_alarm.kill_switch.alarm_name,
    ],
  )
}
