variable "region" {
  type        = string
  default     = "eu-west-2"
  description = "AWS region. Only eu-west-2 is allowed (PRD section 10.2)."

  validation {
    condition     = var.region == "eu-west-2"
    error_message = "Graveyard runs in eu-west-2 only."
  }
}

variable "allowed_account_ids" {
  type        = list(string)
  description = "The one AWS account this root may touch. Supplied at run time (TF_VAR_allowed_account_ids in CI, the git-ignored terraform.tfvars locally), never committed (INF-CFG-2)."

  validation {
    condition     = length(var.allowed_account_ids) == 1 && can(regex("^[0-9]{12}$", var.allowed_account_ids[0]))
    error_message = "Give exactly one 12-digit account ID."
  }
}
