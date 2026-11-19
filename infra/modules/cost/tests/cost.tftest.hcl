# Offline tests for the cost module (INF-COST-1..6, INF-TAG-4, decisions SA1, SA2, F2, C8, O2). The budget
# and the anomaly monitor are filtered to the Project tag; the module imports and reads nothing.

mock_provider "aws" {}

override_resource {
  target          = aws_ce_anomaly_monitor.project
  override_during = plan
  values          = { arn = "arn:aws:ce::123456789012:anomalymonitor/00000000-0000-0000-0000-000000000000" }
}

variables {
  alert_emails      = ["alerts@example.com"]
  project_tag_key   = "Project"
  project_tag_value = "graveyard"
}

run "the_budget_is_filtered_to_the_project_tag_and_not_to_the_account" {
  command = plan

  assert {
    condition     = length(aws_budgets_budget.monthly.cost_filter) == 1
    error_message = "The budget must have exactly one cost filter."
  }

  assert {
    condition     = [for f in aws_budgets_budget.monthly.cost_filter : f.name][0] == "TagKeyValue"
    error_message = "The filter must be a TagKeyValue filter."
  }

  assert {
    condition     = join(",", [for f in aws_budgets_budget.monthly.cost_filter : join(",", f.values)]) == "user:Project$graveyard"
    error_message = "The filter value must be user:Project$graveyard, key and value as in the PRD tag set."
  }

  assert {
    condition     = aws_budgets_budget.monthly.budget_type == "COST" && aws_budgets_budget.monthly.time_unit == "MONTHLY"
    error_message = "The budget must be a monthly cost budget."
  }

  assert {
    condition     = aws_budgets_budget.monthly.name == "graveyard-project-monthly"
    error_message = "The default budget name must be graveyard-project-monthly."
  }
}

run "the_tag_filter_passes_the_case_through_unchanged" {
  command = plan

  variables {
    project_tag_value = "Graveyard"
  }

  assert {
    condition     = join(",", [for f in aws_budgets_budget.monthly.cost_filter : join(",", f.values)]) == "user:Project$Graveyard"
    error_message = "Tag filters are case-sensitive: the case must not be changed."
  }

  assert {
    condition     = jsondecode(aws_ce_anomaly_monitor.project.monitor_specification).Tags.Values == ["Graveyard"]
    error_message = "The monitor must use the same value, unchanged."
  }
}

# The monitor key and the budget filter both come from var.project_tag_key, with "user:" added once.
run "the_user_prefixed_key_comes_from_the_single_tag_key_source" {
  command = plan
  variables {
    project_tag_key = "Team"
  }
  assert {
    condition     = jsondecode(aws_ce_anomaly_monitor.project.monitor_specification).Tags.Key == "user:Team"
    error_message = "The monitor key must be user: plus the tag key variable."
  }
  assert {
    condition     = join(",", [for f in aws_budgets_budget.monthly.cost_filter : join(",", f.values)]) == "user:Team$graveyard"
    error_message = "The budget filter must be user:<key>$<value> from the same variable."
  }
}
run "the_limit_and_the_unit_pass_through" {
  command = plan

  assert {
    condition     = aws_budgets_budget.monthly.limit_amount == "40" && aws_budgets_budget.monthly.limit_unit == "USD"
    error_message = "The default limit must be 40 USD (decision C8)."
  }
}

run "gbp_can_be_chosen" {
  command = plan

  variables {
    budget_limit = { amount = "30", unit = "GBP" }
  }

  assert {
    condition     = aws_budgets_budget.monthly.limit_amount == "30" && aws_budgets_budget.monthly.limit_unit == "GBP"
    error_message = "A GBP limit must pass through."
  }
}

run "there_are_exactly_four_notifications_and_all_go_to_the_email_list" {
  command = plan

  assert {
    condition = toset([
      for n in aws_budgets_budget.monthly.notification : "${n.notification_type}/${n.comparison_operator}/${n.threshold}/${n.threshold_type}"
      ]) == toset([
      "ACTUAL/GREATER_THAN/50/PERCENTAGE",
      "ACTUAL/GREATER_THAN/80/PERCENTAGE",
      "ACTUAL/GREATER_THAN/100/PERCENTAGE",
      "FORECASTED/GREATER_THAN/100/PERCENTAGE",
    ])
    error_message = "The notifications must be actual 50, 80 and 100 percent and forecast 100 percent."
  }

  assert {
    condition     = length(aws_budgets_budget.monthly.notification) == 4
    error_message = "There must be exactly four notifications."
  }

  assert {
    condition     = alltrue([for n in aws_budgets_budget.monthly.notification : toset(n.subscriber_email_addresses) == toset(["alerts@example.com"]) && try(length(n.subscriber_sns_topic_arns), 0) == 0])
    error_message = "Notifications go to the email list only, with no SNS topic (INF-COST-5)."
  }
}

run "the_anomaly_monitor_is_custom_on_the_project_tag" {
  command = plan

  assert {
    condition     = aws_ce_anomaly_monitor.project.monitor_type == "CUSTOM"
    error_message = "The monitor must be a CUSTOM monitor, not a DIMENSIONAL one (SA2)."
  }

  assert {
    condition     = aws_ce_anomaly_monitor.project.monitor_dimension == null
    error_message = "A custom monitor has no monitor_dimension."
  }

  assert {
    condition     = join(",", sort(keys(jsondecode(aws_ce_anomaly_monitor.project.monitor_specification)))) == "And,CostCategories,Dimensions,Not,Or,ProductAttributes,Tags"
    error_message = "The specification must have the six keys of the provider's example and ProductAttributes, which AWS returns as null."
  }

  assert {
    condition     = alltrue([for k in ["And", "CostCategories", "Dimensions", "Not", "Or", "ProductAttributes"] : jsondecode(aws_ce_anomaly_monitor.project.monitor_specification)[k] == null])
    error_message = "Only Tags may be set in the specification."
  }

  assert {
    condition     = jsondecode(aws_ce_anomaly_monitor.project.monitor_specification).Tags == { Key = "user:Project", MatchOptions = null, Values = ["graveyard"] }
    error_message = "The Tags expression must be Key user:Project, Values graveyard, and the API default match options."
  }
  # The exact text that Terraform sends and compares with what AWS returns (V15). Any difference is a perpetual diff.
  assert {
    condition     = aws_ce_anomaly_monitor.project.monitor_specification == "{\"And\":null,\"CostCategories\":null,\"Dimensions\":null,\"Not\":null,\"Or\":null,\"ProductAttributes\":null,\"Tags\":{\"Key\":\"user:Project\",\"MatchOptions\":null,\"Values\":[\"graveyard\"]}}"
    error_message = "The rendered monitor_specification must be exactly the form AWS stores."
  }
  assert {
    condition     = aws_ce_anomaly_monitor.project.tags != null && length(aws_ce_anomaly_monitor.project.tags) == 0
    error_message = "tags must be an explicit empty map (AWS returns {}), or every plan shows {} -> null."
  }

  assert {
    condition     = aws_ce_anomaly_monitor.project.name == "graveyard-project"
    error_message = "The default monitor name must be graveyard-project."
  }
}

run "the_subscription_is_daily_email_on_this_modules_monitor_only" {
  command = plan

  assert {
    condition     = aws_ce_anomaly_subscription.email.frequency == "DAILY"
    error_message = "Email subscriptions are DAILY (IMMEDIATE needs SNS)."
  }

  assert {
    condition     = join(",", aws_ce_anomaly_subscription.email.monitor_arn_list) == "arn:aws:ce::123456789012:anomalymonitor/00000000-0000-0000-0000-000000000000"
    error_message = "The subscription must reference only the monitor this module creates."
  }

  assert {
    condition     = length(aws_ce_anomaly_subscription.email.subscriber) == 1 && [for s in aws_ce_anomaly_subscription.email.subscriber : s.type][0] == "EMAIL" && [for s in aws_ce_anomaly_subscription.email.subscriber : s.address][0] == "alerts@example.com"
    error_message = "There must be one EMAIL subscriber per address."
  }

  assert {
    condition = (
      join(",", flatten([for t in aws_ce_anomaly_subscription.email.threshold_expression : [for d in t.dimension : d.key]])) == "ANOMALY_TOTAL_IMPACT_ABSOLUTE" &&
      join(",", flatten([for t in aws_ce_anomaly_subscription.email.threshold_expression : [for d in t.dimension : join(",", d.match_options)]])) == "GREATER_THAN_OR_EQUAL" &&
      join(",", flatten([for t in aws_ce_anomaly_subscription.email.threshold_expression : [for d in t.dimension : join(",", d.values)]])) == "10"
    )
    error_message = "The threshold must be an absolute impact of at least 10 (decision O2)."
  }
}

run "several_addresses_give_several_subscribers" {
  command = plan

  variables {
    alert_emails = ["a@example.com", "b@example.com"]
  }

  assert {
    condition     = toset([for s in aws_ce_anomaly_subscription.email.subscriber : s.address]) == toset(["a@example.com", "b@example.com"])
    error_message = "Each address must be a subscriber."
  }

  assert {
    condition     = alltrue([for n in aws_budgets_budget.monthly.notification : toset(n.subscriber_email_addresses) == toset(["a@example.com", "b@example.com"])])
    error_message = "Each notification must list every address."
  }
}

run "the_threshold_is_a_variable" {
  command = plan

  variables {
    anomaly_threshold_amount = 25
  }

  assert {
    condition     = join(",", flatten([for t in aws_ce_anomaly_subscription.email.threshold_expression : [for d in t.dimension : join(",", d.values)]])) == "25"
    error_message = "The threshold must follow the variable."
  }
}

run "no_cost_allocation_tag_resource_by_default" {
  command = plan

  assert {
    condition     = length(aws_ce_cost_allocation_tag.key) == 0
    error_message = "By default no cost allocation tag is managed (F2): they may already be active."
  }
}

run "only_the_keys_asked_for_are_activated" {
  command = plan

  variables {
    activate_cost_allocation_tag_keys = ["Project"]
  }

  assert {
    condition     = toset(keys(aws_ce_cost_allocation_tag.key)) == toset(["Project"]) && aws_ce_cost_allocation_tag.key["Project"].status == "Active" && aws_ce_cost_allocation_tag.key["Project"].tag_key == "Project"
    error_message = "Only Project must be activated."
  }
}

run "both_keys_can_be_activated" {
  command = plan

  variables {
    activate_cost_allocation_tag_keys = ["Project", "Env"]
  }

  assert {
    condition     = toset(keys(aws_ce_cost_allocation_tag.key)) == toset(["Project", "Env"])
    error_message = "Both keys must be activated when asked."
  }
}

run "an_unknown_tag_key_is_rejected" {
  command = plan

  variables {
    activate_cost_allocation_tag_keys = ["Owner"]
  }

  expect_failures = [var.activate_cost_allocation_tag_keys]
}

run "eur_is_rejected" {
  command = plan

  variables {
    budget_limit = { amount = "40", unit = "EUR" }
  }

  expect_failures = [var.budget_limit]
}

run "a_non_numeric_or_zero_amount_is_rejected" {
  command = plan

  variables {
    budget_limit = { amount = "0", unit = "USD" }
  }

  expect_failures = [var.budget_limit]
}

run "an_empty_email_list_is_rejected" {
  command = plan

  variables {
    alert_emails = []
  }

  expect_failures = [var.alert_emails]
}

run "more_than_ten_addresses_are_rejected" {
  command = plan

  variables {
    alert_emails = [for i in range(11) : "u${i}@example.com"]
  }

  expect_failures = [var.alert_emails]
}

run "an_address_that_is_not_an_email_is_rejected" {
  command = plan

  variables {
    alert_emails = ["not-an-email"]
  }

  expect_failures = [var.alert_emails]
}

run "an_empty_tag_key_is_rejected" {
  command = plan

  variables {
    project_tag_key = ""
  }

  expect_failures = [var.project_tag_key]
}

run "a_zero_threshold_is_rejected" {
  command = plan

  variables {
    anomaly_threshold_amount = 0
  }

  expect_failures = [var.anomaly_threshold_amount]
}

run "names_must_be_graveyard_names" {
  command = plan

  variables {
    budget_name = "monthly"
  }

  expect_failures = [var.budget_name]
}
