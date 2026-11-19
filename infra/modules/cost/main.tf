locals {
  # Cost Explorer and Budgets address a user-defined cost allocation tag as "user:<Key>". It is built from the one
  # Project tag-key source (var.project_tag_key); there is no second literal.
  user_tag_key = format("user:%s", var.project_tag_key)
  # Budgets tag filter format is "user:<Key>$<Value>" (provider docs, V14). format() keeps the $ literal.
  budget_tag_filter = format("%s$%s", local.user_tag_key, var.project_tag_value)
  # The custom monitor watches Graveyard-tagged spend only (SA2). This is the form AWS stores and returns (V15,
  # first real re-plan 19 Nov 2026): Tags.Key is "user:Project", ProductAttributes is returned as null, and the other
  # siblings and MatchOptions are null, so the API default (EQUALS, CASE_SENSITIVE) applies. Any other form shows
  # as a diff that forces replacement on every plan.
  monitor_specification = jsonencode({
    And               = null
    CostCategories    = null
    Dimensions        = null
    Not               = null
    Or                = null
    ProductAttributes = null
    Tags = {
      Key          = local.user_tag_key
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
  # AWS returns tags = {} for this resource. An explicit empty map matches it, so there is no {} -> null diff. The
  # provider's default_tags still apply: they are merged into tags_all, not into this argument.
  tags = {}
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
