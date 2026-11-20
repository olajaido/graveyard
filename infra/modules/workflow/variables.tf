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
variable "table_name" {
  type        = string
  description = "Name of the DynamoDB single table."
}
variable "table_arn" {
  type        = string
  description = "ARN of the table."
}
variable "bucket_name" {
  type        = string
  description = "Name of the artefacts bucket."
}
variable "bucket_arn" {
  type        = string
  description = "ARN of the artefacts bucket."
}
variable "kms_key_arn" {
  type        = string
  description = "ARN of the app CMK."
}
variable "reader_secret_arn" {
  type        = string
  description = "ARN of the Reader app secret."
}
variable "reader_secret_name" {
  type        = string
  description = "Name of the Reader app secret, graveyard/<env>/github/reader. Passed to the functions as a name, never the value."
}
variable "ssm_parameter_arn_pattern" {
  type        = string
  description = "ARN pattern of the env's SSM parameters."
}
variable "lambda_zip_path" {
  type        = string
  description = "Path of lambda.zip (scripts/build/build_lambda_zip.py)."
}
variable "lambda_zip_sha256" {
  type        = string
  description = "Hex SHA-256 of lambda.zip, from the CI build step (SB-CI-2)."
}
variable "syft_layer_zip_path" {
  type        = string
  description = "Path of syft-layer.zip (scripts/build/build_syft_layer.py)."
}
variable "syft_layer_sha256" {
  type        = string
  description = "Hex SHA-256 of syft-layer.zip, from the CI build step (SB-CI-2)."
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.syft_layer_sha256))
    error_message = "syft_layer_sha256 must be 64 lower-case hex characters."
  }
}
variable "functions" {
  type = map(object({
    memory_size          = number
    timeout              = number
    reserved_concurrency = number
  }))
  default = {
    validate = { memory_size = 256, timeout = 10, reserved_concurrency = 3 }
    fetch    = { memory_size = 512, timeout = 120, reserved_concurrency = 5 }
    syft     = { memory_size = 1024, timeout = 120, reserved_concurrency = 5 }
    graph    = { memory_size = 1024, timeout = 120, reserved_concurrency = 3 }
    autopsy  = { memory_size = 512, timeout = 180, reserved_concurrency = 20 }
    classify = { memory_size = 1024, timeout = 120, reserved_concurrency = 3 }
    finalise = { memory_size = 256, timeout = 10, reserved_concurrency = 3 }
  }
  description = "Memory, timeout and reserved concurrency of the seven task functions. The defaults total 42 for the tasks; with the api function (8) a env stays at about 50 (SB-INF-3). The account limit of 400 is shared."
  validation {
    condition     = toset(keys(var.functions)) == toset(["validate", "fetch", "syft", "graph", "autopsy", "classify", "finalise"])
    error_message = "Give exactly validate, fetch, syft, graph, autopsy, classify and finalise."
  }
}
variable "autopsy_batch_size" {
  type        = number
  default     = 50
  description = "MaxItemsPerBatch of the AutopsyMap ItemBatcher (PRD section 10.6)."
}
variable "autopsy_map_concurrency" {
  type        = number
  default     = 20
  description = "MaxConcurrency of the AutopsyMap. Keep it equal to the reserved concurrency of the autopsy function."
}
variable "sbom_map_concurrency" {
  type        = number
  default     = 5
  description = "MaxConcurrency of the GenerateSBOM map. Keep it at or below the reserved concurrency of the syft function."
}
variable "tolerated_failure_percentage" {
  type        = number
  default     = 20
  description = "Percentage of AutopsyMap batches that may fail without failing the scan (SB-AUT-4)."
  validation {
    condition     = var.tolerated_failure_percentage >= 0 && var.tolerated_failure_percentage <= 100
    error_message = "A percentage from 0 to 100."
  }
}
variable "workflow_timeout_seconds" {
  type        = number
  default     = 300
  description = "Timeout of the whole scan (PRD section 10.6)."
}
variable "log_retention_days" {
  type        = number
  default     = 30
  description = "Retention of the function and state machine log groups."
}
