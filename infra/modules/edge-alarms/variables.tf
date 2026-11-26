variable "name_prefix" {
  type        = string
  description = "graveyard-<env>. The topic and the alarms start with it (INF-NAME-1)."
  validation {
    condition     = can(regex("^graveyard-(dev|prod)$", var.name_prefix))
    error_message = "name_prefix must be graveyard-dev or graveyard-prod."
  }
}
variable "site_distribution_id" {
  type        = string
  description = "ID of the site distribution, from edge-site."
  validation {
    condition     = can(regex("^E[A-Z0-9]{8,20}$", var.site_distribution_id))
    error_message = "A CloudFront distribution ID starts with E."
  }
}
variable "api_distribution_id" {
  type        = string
  description = "ID of the API distribution, from edge-api."
  validation {
    condition     = can(regex("^E[A-Z0-9]{8,20}$", var.api_distribution_id))
    error_message = "A CloudFront distribution ID starts with E."
  }
}
variable "error_rate_threshold" {
  type        = number
  default     = 2
  description = "5xx error rate, in percent over 5 minutes, above which an alarm fires. 2 percent matches the API Gateway alarm of terraform.md."
  validation {
    condition     = var.error_rate_threshold > 0 && var.error_rate_threshold <= 100
    error_message = "Give a percentage above 0 and at most 100."
  }
}
variable "min_requests" {
  type        = number
  default     = 10
  description = "An alarm is evaluated only when the distribution had at least this many requests in the same 5 minutes; otherwise its value is 0. One failed request at demo traffic would otherwise read as 100 percent."
  validation {
    condition     = var.min_requests >= 1 && floor(var.min_requests) == var.min_requests
    error_message = "Give a whole number, 1 or more."
  }
}
