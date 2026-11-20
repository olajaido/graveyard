variable "name" {
  type        = string
  description = "Full function name, graveyard-<env>-<function> (INF-NAME-1). Also the name of its role and log group."
  validation {
    condition     = can(regex("^graveyard-(dev|prod)-[a-z0-9-]{1,40}$", var.name))
    error_message = "The name must look like graveyard-<env>-<function>."
  }
}
variable "env" {
  type        = string
  description = "dev or prod. Used for the role path /graveyard-<env>/."
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}
variable "account_id" {
  type        = string
  description = "AWS account ID, from the root's aws_caller_identity. Only used to build ARNs."
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
variable "boundary_arn" {
  type        = string
  description = "ARN of the env's workload boundary, graveyard-<env>-boundary (INF-APPLY-4). Every role carries it."
  validation {
    condition     = can(regex("^arn:[a-z-]+:iam::[0-9]{12}:policy/graveyard-ci/graveyard-(dev|prod)-boundary$", var.boundary_arn))
    error_message = "boundary_arn must be a graveyard-<env>-boundary policy ARN."
  }
}
variable "handler" {
  type        = string
  description = "Handler, module.function. For example workflow.fetch.handler."
}
variable "filename" {
  type        = string
  description = "Path of lambda.zip, built by scripts/build/build_lambda_zip.py."
}
variable "zip_sha256" {
  type        = string
  description = "Hex SHA-256 of lambda.zip, built in the same CI job. The module fails when the file differs, so a different zip cannot be uploaded under a saved plan (SB-CI-2)."
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.zip_sha256))
    error_message = "zip_sha256 must be 64 lower-case hex characters."
  }
}
variable "layers" {
  type        = list(string)
  default     = []
  description = "ARNs of layer versions."
}
variable "memory_size" {
  type        = number
  default     = 512
  description = "Memory in MB."
}
variable "timeout" {
  type        = number
  default     = 30
  description = "Timeout in seconds."
}
variable "reserved_concurrency" {
  type        = number
  description = "Reserved concurrent executions. The account limit is shared, so every function sets it (SB-INF-3)."
  validation {
    condition     = var.reserved_concurrency >= 1
    error_message = "Reserve at least 1."
  }
}
variable "environment" {
  type        = map(string)
  default     = {}
  description = "Environment variables. Names of resources only: never a secret or a token (SB-CFG-3)."
}
variable "statements" {
  type        = any
  default     = []
  description = "IAM policy statements (a list of objects) for this function, on top of its own logs and X-Ray. Built with jsonencode-ready objects in the caller's locals."
}
variable "log_retention_days" {
  type        = number
  default     = 30
  description = "Retention of the function's log group, in days."
}
