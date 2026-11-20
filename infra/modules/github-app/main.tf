# The Graveyard Reader GitHub App's secret container and its two identifiers (SB-CFG-1, SB-CFG-2, security.md).
# Terraform creates the empty container only. The PEM private key is put in by hand (SB-MAN-1) and never appears in
# Terraform, a variable or the state. The App ID and installation ID are not secrets; they start as UNSET.
locals {
  secret_name = "graveyard/${var.env}/github/reader"
  ssm_prefix  = "/graveyard/${var.env}/github/reader"
  identifiers = toset(["app-id", "installation-id"])
}
resource "aws_secretsmanager_secret" "reader" {
  name                    = local.secret_name
  description             = "Private key (PEM) of the Graveyard Reader GitHub App. Set by hand."
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
  # checkov:skip=CKV2_AWS_57:The key is a GitHub App private key; GitHub rotates by replacing it (runbook, 90 days). Secrets Manager rotation does not apply (security.md).
}
resource "aws_ssm_parameter" "identifier" {
  for_each = local.identifiers
  name     = "${local.ssm_prefix}/${each.key}"
  type     = "String"
  value    = "UNSET"
  # checkov:skip=CKV2_AWS_34:The App ID and installation ID are identifiers, not secrets (security.md).
  # The maintainer sets the real value by hand after the first apply (SB-MAN-1). Terraform keeps the parameter, not its value.
  lifecycle {
    ignore_changes = [value]
  }
}
