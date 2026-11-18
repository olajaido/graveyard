variable "account_id" {
  type        = string
  description = "AWS account ID. Read by the root from its caller identity; modules declare no data sources (INF-POL-1)."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be 12 digits."
  }
}

variable "partition" {
  type        = string
  description = "AWS partition. Read by the root; modules declare no data sources (INF-POL-1)."

  validation {
    condition     = contains(["aws", "aws-cn", "aws-us-gov"], var.partition)
    error_message = "partition must be aws, aws-cn or aws-us-gov."
  }
}

variable "region" {
  type        = string
  default     = "eu-west-2"
  description = "Region of the state bucket. Only eu-west-2 is allowed (PRD section 10.2)."

  validation {
    condition     = var.region == "eu-west-2"
    error_message = "Graveyard runs in eu-west-2 only."
  }
}

variable "bucket_name_prefix" {
  type        = string
  default     = "graveyard-tfstate"
  description = "Prefix of the state bucket name. A random suffix is added, so the name is unique without the account ID."

  validation {
    condition     = startswith(var.bucket_name_prefix, "graveyard-")
    error_message = "The bucket name must start with graveyard- (INF-SHARED-1)."
  }
}

variable "ci_role_arns" {
  type = object({
    plan  = string
    apply = map(string)
  })
  description = "ARNs of the CI roles that may use the state key, from the github-oidc module outputs. KMS rejects a key policy that names a role that does not exist, so the root passes the role resources' ARNs."
}

variable "state_noncurrent_days" {
  type        = number
  default     = 90
  description = "Days after which a noncurrent state version expires (INF-STATE-3)."

  validation {
    condition     = var.state_noncurrent_days >= 1
    error_message = "state_noncurrent_days must be at least 1."
  }
}

variable "state_noncurrent_keep" {
  type        = number
  default     = 10
  description = "Number of newest noncurrent state versions to keep regardless of age (INF-STATE-3)."

  validation {
    condition     = var.state_noncurrent_keep >= 1
    error_message = "state_noncurrent_keep must be at least 1."
  }
}

variable "plans_expiry_days" {
  type        = number
  default     = 7
  description = "Days after which a saved plan under plans/ expires (decision C5: at most 7)."

  validation {
    condition     = var.plans_expiry_days >= 1 && var.plans_expiry_days <= 7
    error_message = "plans_expiry_days must be between 1 and 7."
  }
}
