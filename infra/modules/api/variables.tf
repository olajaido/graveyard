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
  description = "ARN of the env's workload boundary (INF-APPLY-4)."
}
variable "table_arn" {
  type        = string
  description = "ARN of the DynamoDB single table."
}
variable "table_name" {
  type        = string
  description = "Name of the table."
}
variable "table_index_arn" {
  type        = string
  description = "ARN of GSI1."
}
variable "kms_key_arn" {
  type        = string
  description = "ARN of the app CMK."
}
variable "ssm_parameter_arn_pattern" {
  type        = string
  description = "ARN pattern of the env's SSM parameters."
}
variable "state_machine_arn" {
  type        = string
  description = "ARN of the scan state machine."
}
variable "state_machine_alias_arn" {
  type        = string
  description = "ARN of the live alias of the scan state machine. The API starts executions through it."
}
variable "lambda_zip_path" {
  type        = string
  description = "Path of lambda.zip (scripts/build/build_lambda_zip.py)."
}
variable "lambda_zip_sha256" {
  type        = string
  description = "Hex SHA-256 of lambda.zip, from the CI build step (SB-CI-2)."
}
variable "routes" {
  type = list(string)
  default = [
    "POST /v1/scans",
    "GET /v1/scans/{scanId}",
    "GET /v1/scans/{scanId}/graves",
    "GET /v1/scans/{scanId}/graves/{purl+}",
  ]
  description = "Route keys of the API (SB-API-7). They equal backend/api/routes.py ROUTES and the paths of backend/api/openapi.yaml; the CI guard api-routes compares them."
}
variable "post_route_key" {
  type        = string
  default     = "POST /v1/scans"
  description = "The route that starts scans. It gets the lower throttle of SB-API-9."
}
variable "memory_size" {
  type        = number
  default     = 512
  description = "Memory of the api function in MB."
}
variable "timeout" {
  type        = number
  default     = 15
  description = "Timeout of the api function in seconds."
}
variable "reserved_concurrency" {
  type        = number
  default     = 8
  description = "Reserved concurrency of the api function (SB-INF-3)."
}
variable "default_rate_limit" {
  type        = number
  default     = 50
  description = "Steady requests per second for every route."
}
variable "default_burst_limit" {
  type        = number
  default     = 100
  description = "Burst for every route."
}
variable "post_rate_limit" {
  type        = number
  default     = 2
  description = "Steady requests per second for POST /v1/scans, lower than the reads (SB-API-9)."
}
variable "post_burst_limit" {
  type        = number
  default     = 5
  description = "Burst for POST /v1/scans."
}
variable "cors_allowed_origins" {
  type        = list(string)
  default     = []
  description = "Browser origins allowed by CORS. Empty by default: no browser origin (SB-API-9)."
  validation {
    condition     = !contains(var.cors_allowed_origins, "*")
    error_message = "List the origins; * is not allowed."
  }
}
variable "log_retention_days" {
  type        = number
  default     = 30
  description = "Retention of the function and access log groups."
}
