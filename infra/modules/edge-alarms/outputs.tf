output "topic_arn" {
  description = "ARN of the edge alerts topic in us-east-1. Subscribe to it by hand (EDGE-MAN-4)."
  value       = aws_sns_topic.edge.arn
}
output "alarm_names" {
  description = "Names of the two alarms."
  value       = [for a in aws_cloudwatch_metric_alarm.cdn_5xx : a.alarm_name]
}
