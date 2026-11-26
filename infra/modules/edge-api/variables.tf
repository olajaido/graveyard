variable "name_prefix" {
  type        = string
  description = "graveyard-<env>. The headers function starts with it (INF-NAME-1)."
  validation {
    condition     = can(regex("^graveyard-(dev|prod)$", var.name_prefix))
    error_message = "name_prefix must be graveyard-dev or graveyard-prod."
  }
}
variable "api_host" {
  type        = string
  description = "Host name of the API: api.lastrites.dev in prod, api.dev.lastrites.dev in dev."
  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.api_host))
    error_message = "Give a lower-case host name with no scheme, no wildcard and no trailing dot."
  }
}
variable "api_endpoint" {
  type        = string
  description = "Execute endpoint of the HTTP API's $default stage, https://<id>.execute-api.<region>.amazonaws.com, from the api module. The distribution's only origin. The default stage has no path prefix."
  validation {
    condition     = can(regex("^https://[a-z0-9]+\\.execute-api\\.[a-z0-9-]+\\.amazonaws\\.com$", var.api_endpoint))
    error_message = "Give the execute-api endpoint with https:// and no path."
  }
}
variable "certificate_arn" {
  type        = string
  description = "ARN of the issued us-east-1 ACM certificate that covers the API host, from edge-cert."
  validation {
    condition     = can(regex("^arn:[a-z-]+:acm:us-east-1:", var.certificate_arn))
    error_message = "A CloudFront certificate must be an ACM certificate in us-east-1."
  }
}
variable "web_acl_arn" {
  type        = string
  default     = null
  description = "ARN of the Edge ACL (WAFv2, scope CLOUDFRONT), or null when the env has none (dev by default, R7)."
  validation {
    condition     = var.web_acl_arn == null || can(regex("^arn:[a-z-]+:wafv2:us-east-1:[0-9]{12}:global/webacl/", var.web_acl_arn))
    error_message = "Give a global (CloudFront scope) web ACL ARN in us-east-1, or null."
  }
}
variable "zone_id" {
  type        = string
  description = "ID of the existing public hosted zone that gets the alias records. The zone is not managed here (EDGE-DNS-1)."
  validation {
    condition     = can(regex("^Z[A-Z0-9]{3,40}$", var.zone_id))
    error_message = "A hosted zone ID starts with Z and holds only capital letters and digits."
  }
}
variable "price_class" {
  type        = string
  default     = "PriceClass_100"
  description = "CloudFront price class (EDGE-COST-1)."
  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)
    error_message = "Use PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}
