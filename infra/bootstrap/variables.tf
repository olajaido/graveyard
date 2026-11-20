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
  description = "The one AWS account this root may touch. Supplied at run time from the git-ignored terraform.tfvars, never committed (INF-CFG-2)."

  validation {
    condition     = length(var.allowed_account_ids) == 1 && can(regex("^[0-9]{12}$", var.allowed_account_ids[0]))
    error_message = "Give exactly one 12-digit account ID."
  }
}

variable "repo_owner" {
  type        = string
  default     = "olajaido"
  description = "GitHub owner of the repository that may assume the CI roles."
}

variable "repo_name" {
  type        = string
  default     = "graveyard"
  description = "GitHub repository name."
}

variable "repo_owner_id" {
  type        = string
  default     = "102736714"
  description = "Numeric GitHub ID of the repository owner (public). From `gh api repos/<owner>/<repo>/actions/oidc/customization/sub`: sub_claim_prefix is repo:<owner>@<owner id>/<repo>@<repo id>."
}
variable "repo_id" {
  type        = string
  default     = "1443508961"
  description = "Numeric GitHub ID of the repository (public). See repo_owner_id."
}
variable "create_oidc_provider" {
  type        = bool
  default     = false
  description = "Default false: the shared account already has a GitHub OIDC provider owned by another project, and this root never imports, reads or manages it (SA3). Set true only if that provider no longer exists; creating one while it exists fails with an already-exists error, which is safe."
}

variable "alert_emails" {
  type        = list(string)
  description = "Addresses for the budget and anomaly notifications, 1 to 10. Supplied from the git-ignored terraform.tfvars, never committed (INF-COST-5)."
}

variable "budget_limit" {
  type = object({
    amount = string
    unit   = string
  })
  default = {
    amount = "40"
    unit   = "USD"
  }
  description = "Monthly limit for Graveyard-tagged spend. Default 40 USD (decision C8). If the account bills in GBP, set { amount = \"30\", unit = \"GBP\" } (PRD section 12: 30 pounds a month)."
}

variable "anomaly_monitor_name" {
  type        = string
  default     = "graveyard-project"
  description = "Name of the custom anomaly monitor this root creates. Nothing is imported."
}

variable "anomaly_threshold_amount" {
  type        = number
  default     = 10
  description = "Absolute anomaly impact at which the subscription emails (decision O2: 10, in the account currency)."
}

variable "activate_cost_allocation_tag_keys" {
  type        = set(string)
  default     = []
  description = "Cost allocation tag keys to activate. Account-wide (F2): put in only the keys that the Billing console shows as NOT active. Graveyard never manages an already-active key."
}

variable "bedrock_narrate_profile_id" {
  type        = string
  default     = "eu.anthropic.claude-haiku-5-5"
  description = "EU inference profile ID that narrate uses (PRD section 10.2). Exact ARN in the workload boundaries only (INF-SHARED-6)."

  validation {
    condition     = can(regex("^eu\\.[A-Za-z0-9._:-]+$", var.bedrock_narrate_profile_id))
    error_message = "The profile ID must start with eu. (never global.) and contain no wildcard."
  }
}

variable "bedrock_rites_profile_id" {
  type        = string
  default     = "eu.anthropic.claude-sonnet-5-5"
  description = "EU inference profile ID that rites use (PRD section 10.2). Exact ARN in the workload boundaries only (INF-SHARED-6)."

  validation {
    condition     = can(regex("^eu\\.[A-Za-z0-9._:-]+$", var.bedrock_rites_profile_id))
    error_message = "The profile ID must start with eu. (never global.) and contain no wildcard."
  }
}

variable "bedrock_foundation_model_regions" {
  type        = list(string)
  default     = ["eu-central-1", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-2", "eu-west-3"]
  description = "Regions the two eu. profiles route to, as read by the maintainer from list-inference-profiles in eu-west-2 on 18 Nov 2026. Exact regions only, never eu-*. A routing change needs a reviewed change here."

  validation {
    condition     = length(var.bedrock_foundation_model_regions) > 0 && alltrue([for r in var.bedrock_foundation_model_regions : can(regex("^eu-[a-z]+-[0-9]+$", r))])
    error_message = "Give at least one exact EU region such as eu-west-2, with no wildcard."
  }
}
