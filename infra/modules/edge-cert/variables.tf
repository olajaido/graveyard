variable "domain_names" {
  type        = list(string)
  description = "Every hostname the env serves, for example [dev.lastrites.dev, api.dev.lastrites.dev]. The first is the certificate's primary name and the rest are alternative names (EDGE-CERT-1)."
  validation {
    condition     = length(var.domain_names) > 0 && length(var.domain_names) <= 10 && length(distinct(var.domain_names)) == length(var.domain_names)
    error_message = "Give between 1 and 10 distinct hostnames."
  }
  validation {
    condition     = alltrue([for n in var.domain_names : can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", n))])
    error_message = "Hostnames must be lower-case, with no wildcard, no trailing dot and no scheme."
  }
}
variable "zone_id" {
  type        = string
  description = "ID of the existing public hosted zone that holds the validation records. The zone is made by hand; this module only writes records (EDGE-DNS-1)."
  validation {
    condition     = can(regex("^Z[A-Z0-9]{3,40}$", var.zone_id))
    error_message = "A hosted zone ID starts with Z and holds only capital letters and digits."
  }
}
