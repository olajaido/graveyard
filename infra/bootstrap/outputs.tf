output "state_bucket_name" {
  description = "Name of the state bucket (graveyard-tfstate-<random suffix>). Goes into backend.hcl and the GitHub variable TF_STATE_BUCKET. Not a secret."
  value       = module.state.bucket_name
}

output "state_kms_key_id" {
  description = "ID (UUID) of the state KMS key. Goes into the GitHub variable TF_STATE_KMS_KEY_ID. Not a secret."
  value       = module.state.kms_key_id
}

output "state_kms_key_arn" {
  description = "ARN of the state KMS key, for the local backend.hcl. It contains the account ID: do not commit it."
  value       = module.state.kms_key_arn
}

output "ci_role_names" {
  description = "Names (not ARNs) of the CI roles. Workflows build the ARNs from the account ID secret."
  value = {
    plan  = module.github_oidc.plan_role_name
    apply = module.github_oidc.apply_role_names
  }
}

output "anomaly_monitor_arn" {
  description = "ARN of the custom anomaly monitor this root created."
  value       = module.cost.anomaly_monitor_arn
}
