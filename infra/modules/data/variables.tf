variable "name_prefix" {
  type        = string
  description = "graveyard-<env>. Every named resource starts with it (INF-NAME-1)."
  validation {
    condition     = can(regex("^graveyard-(dev|prod)$", var.name_prefix))
    error_message = "name_prefix must be graveyard-dev or graveyard-prod."
  }
}
variable "env" {
  type        = string
  description = "dev or prod."
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}
variable "account_id" {
  type        = string
  description = "AWS account ID, from the root's aws_caller_identity."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Give a 12-digit account ID."
  }
}
variable "partition" {
  type        = string
  default     = "aws"
  description = "AWS partition, from the root's aws_partition."
}
variable "region" {
  type        = string
  default     = "eu-west-2"
  description = "AWS region. Only eu-west-2 is allowed."
  validation {
    condition     = var.region == "eu-west-2"
    error_message = "Graveyard runs in eu-west-2 only."
  }
}
variable "limits" {
  type = object({
    max_services       = number
    max_manifest_bytes = number
    max_file_bytes     = number
    max_purls          = number
  })
  default = {
    max_services       = 50
    max_manifest_bytes = 10485760
    max_file_bytes     = 5242880
    max_purls          = 2000
  }
  description = "Scan limits written to SSM (SB-CFG-1). Defaults are PRD section 10.6 and requirements SB-FET-4."
}
variable "contact" {
  type        = string
  description = "Contact string for the User-Agent of the source clients (SB-CFG-1). An address or URL of the maintainer; not a secret."
  validation {
    condition     = length(var.contact) >= 3 && length(var.contact) <= 100
    error_message = "Give a contact of 3 to 100 characters."
  }
}
variable "key_deletion_window_days" {
  type        = number
  default     = 30
  description = "Waiting period when the key is scheduled for deletion."
}
variable "noncurrent_version_days" {
  type        = number
  default     = 1
  description = "Days after which noncurrent object versions expire."
}
