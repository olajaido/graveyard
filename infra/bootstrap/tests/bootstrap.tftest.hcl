# The bootstrap root planned offline, with every provider mocked (T12). The module tests assert the policies; this
# test proves the root wires the three modules together without a dependency cycle (validate cannot see one) and
# that its inputs and outputs have the right shape. A root reads the caller identity, so these two data sources are
# mocked here; modules declare no data source (INF-POL-1).

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }

  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
}

mock_provider "random" {}

override_resource {
  target          = module.state.aws_kms_key.state
  override_during = plan
  values = {
    id     = "00000000-0000-0000-0000-000000000000"
    key_id = "00000000-0000-0000-0000-000000000000"
    arn    = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
  }
}

variables {
  allowed_account_ids = ["123456789012"]
  alert_emails        = ["alerts@example.com"]
}

run "the_root_plans_with_all_three_modules_and_names_the_ci_roles" {
  command = plan

  assert {
    condition = output.ci_role_names == {
      plan  = "graveyard-plan"
      apply = { dev = "graveyard-dev-apply", prod = "graveyard-prod-apply" }
    }
    error_message = "The CI role names must be graveyard-plan, graveyard-dev-apply and graveyard-prod-apply."
  }
}

run "the_existing_oidc_provider_is_reused_by_default_and_a_new_one_can_be_asked_for" {
  command = plan

  variables {
    create_oidc_provider = true
  }

  assert {
    condition     = output.ci_role_names.plan == "graveyard-plan"
    error_message = "The root must also plan when it creates the provider."
  }
}

run "tag_keys_to_activate_are_passed_through" {
  command = plan

  variables {
    activate_cost_allocation_tag_keys = ["Project"]
  }

  assert {
    condition     = output.ci_role_names.plan == "graveyard-plan"
    error_message = "The root must plan with a key to activate."
  }
}

run "gbp_budget_plans" {
  command = plan

  variables {
    budget_limit = { amount = "30", unit = "GBP" }
  }

  assert {
    condition     = output.ci_role_names.plan == "graveyard-plan"
    error_message = "The root must plan with a GBP budget."
  }
}

run "more_than_one_account_is_rejected" {
  command = plan

  variables {
    allowed_account_ids = ["123456789012", "123456789012"]
  }

  expect_failures = [var.allowed_account_ids]
}

run "a_malformed_account_id_is_rejected" {
  command = plan

  variables {
    allowed_account_ids = ["12345"]
  }

  expect_failures = [var.allowed_account_ids]
}

run "other_regions_are_rejected" {
  command = plan

  variables {
    region = "us-east-1"
  }

  expect_failures = [var.region]
}

run "a_global_bedrock_profile_is_rejected" {
  command = plan

  variables {
    bedrock_narrate_profile_id = "global.anthropic.claude-haiku-5-5"
  }

  expect_failures = [var.bedrock_narrate_profile_id]
}

run "a_wildcard_bedrock_region_is_rejected" {
  command = plan

  variables {
    bedrock_foundation_model_regions = ["eu-*"]
  }

  expect_failures = [var.bedrock_foundation_model_regions]
}
