# Account-level resources of Graveyard (INF-BOOT-1). Applied only by the maintainer from a workstation
# (INF-BOOT-3). The account is shared with other projects, so nothing here reads or manages a resource
# that this stack did not create.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

module "state" {
  source = "../modules/state"

  account_id         = data.aws_caller_identity.current.account_id
  partition          = data.aws_partition.current.partition
  region             = var.region
  bucket_name_prefix = "graveyard-tfstate"

  # KMS rejects a key policy that names a role that does not exist yet, so these are the role resources' ARNs.
  ci_role_arns = {
    plan  = module.github_oidc.plan_role_arn
    apply = module.github_oidc.apply_role_arns
  }
}

module "github_oidc" {
  source = "../modules/github-oidc"

  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = var.region

  repo_owner           = var.repo_owner
  repo_name            = var.repo_name
  envs                 = ["dev", "prod"]
  ci_path              = "/graveyard-ci/"
  create_oidc_provider = var.create_oidc_provider

  state_bucket_name = module.state.bucket_name
  state_kms_key_arn = module.state.kms_key_arn

  bedrock_narrate_profile_id       = var.bedrock_narrate_profile_id
  bedrock_rites_profile_id         = var.bedrock_rites_profile_id
  bedrock_foundation_model_regions = var.bedrock_foundation_model_regions
}

module "cost" {
  source = "../modules/cost"

  alert_emails                      = var.alert_emails
  budget_limit                      = var.budget_limit
  project_tag_key                   = local.project_tag_key
  project_tag_value                 = local.project_tag_value
  anomaly_monitor_name              = var.anomaly_monitor_name
  anomaly_threshold_amount          = var.anomaly_threshold_amount
  activate_cost_allocation_tag_keys = var.activate_cost_allocation_tag_keys
}
