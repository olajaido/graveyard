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
  description = "dev or prod. Names the metric namespace Graveyard/<env>."
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}
variable "account_id" {
  type        = string
  description = "AWS account ID, from the root's aws_caller_identity. Only used to build the state machine ARN."
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
variable "function_names" {
  type        = list(string)
  description = "Names of every Lambda function to alarm on (the task functions and the api function)."
}
variable "api_function_name" {
  type        = string
  description = "Name of the api function. Its log group carries the kill-switch metric filter."
}
variable "state_machine_name" {
  type        = string
  description = "Name of the scan state machine."
}
variable "api_id" {
  type        = string
  description = "ID of the HTTP API."
}
variable "table_name" {
  type        = string
  description = "Name of the DynamoDB table."
}
