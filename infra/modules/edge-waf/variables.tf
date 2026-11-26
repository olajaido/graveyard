variable "name_prefix" {
  type        = string
  description = "graveyard-<env>. The web ACL is named <prefix>-edge (INF-NAME-1)."
  validation {
    condition     = can(regex("^graveyard-(dev|prod)$", var.name_prefix))
    error_message = "name_prefix must be graveyard-dev or graveyard-prod."
  }
}
variable "scan_rate_limit" {
  type        = number
  default     = 20
  description = "Most POST /v1/scans requests one IP may make in one evaluation window before it is blocked with 429 (EDGE-WAF-2). The scan stage allows 2 POST per second for all callers together, so one IP must not be able to use all of it. WAF accepts 10 or more."
  validation {
    condition     = var.scan_rate_limit >= 10 && var.scan_rate_limit <= 2000000 && floor(var.scan_rate_limit) == var.scan_rate_limit
    error_message = "Give a whole number from 10 to 2,000,000 (the WAF limits)."
  }
}
variable "scan_rate_window_seconds" {
  type        = number
  default     = 300
  description = "Length of the rate window in seconds. WAF accepts 60, 120, 300 or 600."
  validation {
    condition     = contains([60, 120, 300, 600], var.scan_rate_window_seconds)
    error_message = "WAF accepts only 60, 120, 300 or 600 seconds."
  }
}
