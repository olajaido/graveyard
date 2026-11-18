locals {
  # Budgets tag filter format is "user:<Key>$<Value>" (provider docs, V14). format() keeps the $ literal.
  budget_tag_filter = format("user:%s$%s", var.project_tag_key, var.project_tag_value)

  # The custom monitor watches Graveyard-tagged spend only (SA2). The form is the provider's own example, with the
  # other five expression keys null and MatchOptions null so the API default (EQUALS, CASE_SENSITIVE) applies (V15).
  monitor_specification = jsonencode({
    And            = null
    CostCategories = null
    Dimensions     = null
    Not            = null
    Or             = null
    Tags = {
      Key          = var.project_tag_key
      MatchOptions = null
      Values       = [var.project_tag_value]
    }
  })

  budget_notifications = [
    { type = "ACTUAL", threshold = 50 },
    { type = "ACTUAL", threshold = 80 },
    { type = "ACTUAL", threshold = 100 },
    { type = "FORECASTED", threshold = 100 },
  ]
}

# Graveyard-tagged spend only, not the account (SA1). It reads 0 until the Project tag is an active cost
# allocation tag and tagged resources have billed (INF-TAG-4, V7).
resource "aws_budgets_budget" "monthly" {
  name         = var.budget_name
  budget_type  = "COST"
  time_unit    = "MONTHLY"
  limit_amount = var.budget_limit.amount
  limit_unit   = var.budget_limit.unit

  cost_filter {
    name   = "TagKeyValue"
    values = [local.budget_tag_filter]
  }

  dynamic "notification" {
    for_each = local.budget_notifications

    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = notification.value.type
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = var.alert_emails
    }
  }
}

# A new custom monitor. The account's existing monitors are never read, imported or changed (INF-COST-4).
resource "aws_ce_anomaly_monitor" "project" {
  name                  = var.anomaly_monitor_name
  monitor_type          = "CUSTOM"
  monitor_specification = local.monitor_specification
}

# DAILY: AWS sends email for DAILY and WEEKLY; IMMEDIATE needs SNS (V6), and SNS is out of scope (C6).
resource "aws_ce_anomaly_subscription" "email" {
  name             = "${var.anomaly_monitor_name}-daily"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.project.arn]

  dynamic "subscriber" {
    for_each = toset(var.alert_emails)

    content {
      type    = "EMAIL"
      address = subscriber.value
    }
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_threshold_amount)]
    }
  }
}

# Only keys that are not active yet (F2). prevent_destroy: a destroy must not deactivate a key that other
# projects may rely on.
resource "aws_ce_cost_allocation_tag" "key" {
  for_each = var.activate_cost_allocation_tag_keys

  tag_key = each.key
  status  = "Active"

  lifecycle {
    prevent_destroy = true
  }
}
