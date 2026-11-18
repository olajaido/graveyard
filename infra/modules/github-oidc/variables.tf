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
  description = "Region of the Graveyard resources. Only eu-west-2 is allowed (PRD section 10.2)."

  validation {
    condition     = var.region == "eu-west-2"
    error_message = "Graveyard runs in eu-west-2 only."
  }
}

variable "repo_owner" {
  type        = string
  description = "GitHub owner of the repository that may assume the CI roles (INF-OIDC-5). Every trust subject is built from it."

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+$", var.repo_owner))
    error_message = "repo_owner may contain only letters, digits and hyphens, so a trust subject can never hold a wildcard."
  }
}

variable "repo_name" {
  type        = string
  description = "GitHub repository name. Every trust subject is built from it."

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.repo_name))
    error_message = "repo_name may contain only letters, digits, dots, underscores and hyphens, so a trust subject can never hold a wildcard."
  }
}

variable "envs" {
  type        = set(string)
  default     = ["dev", "prod"]
  description = "The environments that get an apply role and a workload boundary."

  validation {
    condition     = length(var.envs) > 0 && alltrue([for e in var.envs : contains(["dev", "prod"], e)])
    error_message = "envs must be a non-empty subset of dev and prod."
  }
}

variable "ci_path" {
  type        = string
  default     = "/graveyard-ci/"
  description = "IAM path of the CI roles, their policies and the workload boundaries. Workload roles use /graveyard-<env>/ and are out of reach of the apply roles' IAM statements on this path."

  validation {
    condition     = startswith(var.ci_path, "/graveyard-") && endswith(var.ci_path, "/")
    error_message = "ci_path must look like /graveyard-<name>/ (INF-SHARED-1)."
  }
}

variable "state_bucket_name" {
  type        = string
  description = "Name of the state bucket, from the state module."

  validation {
    condition     = startswith(var.state_bucket_name, "graveyard-")
    error_message = "The state bucket name must start with graveyard- (INF-SHARED-1)."
  }
}

variable "state_kms_key_arn" {
  type        = string
  description = "ARN of the state KMS key, from the state module."

  validation {
    condition     = startswith(var.state_kms_key_arn, "arn:")
    error_message = "state_kms_key_arn must be an ARN."
  }
}

variable "create_oidc_provider" {
  type        = bool
  default     = false
  description = "Default false: the shared account already has a GitHub OIDC provider owned by another project, and this module never imports, reads or manages it (INF-OIDC-1, INF-OIDC-10). The ARN is built from account_id and partition. Set true only if that provider no longer exists; creating one while it exists fails with an already-exists error, which is safe."
}

variable "bedrock_narrate_profile_id" {
  type        = string
  default     = "eu.anthropic.claude-haiku-5-5"
  description = "EU inference profile ID that narrate uses (PRD section 10.2). Used only by exception E5 in the workload boundaries, as an exact ARN. If the SSM model ID changes, change this too, in a reviewed bootstrap change (INF-SHARED-6)."

  validation {
    condition     = can(regex("^eu\\.[A-Za-z0-9._:-]+$", var.bedrock_narrate_profile_id))
    error_message = "The profile ID must start with eu. (never global.) and contain no wildcard."
  }
}

variable "bedrock_rites_profile_id" {
  type        = string
  default     = "eu.anthropic.claude-sonnet-5-5"
  description = "EU inference profile ID that rites use (PRD section 10.2). Used only by exception E5 in the workload boundaries, as an exact ARN (INF-SHARED-6)."

  validation {
    condition     = can(regex("^eu\\.[A-Za-z0-9._:-]+$", var.bedrock_rites_profile_id))
    error_message = "The profile ID must start with eu. (never global.) and contain no wildcard."
  }
}

variable "bedrock_foundation_model_regions" {
  type        = list(string)
  default     = ["eu-central-1", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-2", "eu-west-3"]
  description = "Regions of the foundation-model ARNs that the two eu. profiles route to. The default is the seven regions that list-inference-profiles in eu-west-2 returned for eu.anthropic.claude-haiku-5-5 and eu.anthropic.claude-sonnet-5-5 (read by the maintainer, 18 Nov 2026). A region that is not listed is denied (fails closed), so a change in routing needs a reviewed change here (design V19). Exact regions only, never eu-*."

  validation {
    condition     = length(var.bedrock_foundation_model_regions) > 0 && alltrue([for r in var.bedrock_foundation_model_regions : can(regex("^eu-[a-z]+-[0-9]+$", r))])
    error_message = "Give at least one EU region such as eu-west-2, with no wildcard."
  }
}
