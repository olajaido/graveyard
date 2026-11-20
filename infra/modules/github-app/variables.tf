variable "env" {
  type        = string
  description = "dev or prod."
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}
variable "kms_key_arn" {
  type        = string
  description = "ARN of the app CMK that encrypts the secret."
}
variable "recovery_window_in_days" {
  type        = number
  default     = 7
  description = "Days a deleted secret can be restored. 7 is the shortest allowed that still protects against a mistake."
  validation {
    condition     = var.recovery_window_in_days >= 7 && var.recovery_window_in_days <= 30
    error_message = "Use 7 to 30 days."
  }
}
