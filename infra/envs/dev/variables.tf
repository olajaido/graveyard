variable "region" {
  type        = string
  default     = "eu-west-2"
  description = "AWS region. Only eu-west-2 is allowed (PRD section 10.2)."

  validation {
    condition     = var.region == "eu-west-2"
    error_message = "Graveyard runs in eu-west-2 only."
  }
}

variable "allowed_account_ids" {
  type        = list(string)
  description = "The one AWS account this root may touch. Supplied at run time (TF_VAR_allowed_account_ids in CI, the git-ignored terraform.tfvars locally), never committed (INF-CFG-2)."

  validation {
    condition     = length(var.allowed_account_ids) == 1 && can(regex("^[0-9]{12}$", var.allowed_account_ids[0]))
    error_message = "Give exactly one 12-digit account ID."
  }
}
variable "lambda_zip_path" {
  type        = string
  default     = "../../../build/lambda.zip"
  description = "Path of lambda.zip, built by scripts/build/build_lambda_zip.py in the same CI job (SB-CI-1)."
}
variable "lambda_zip_sha256" {
  type        = string
  description = "Hex SHA-256 of lambda.zip, printed by the build script. CI passes it as TF_VAR_lambda_zip_sha256 (SB-CI-2)."
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.lambda_zip_sha256))
    error_message = "Give 64 lower-case hex characters."
  }
}
variable "syft_layer_zip_path" {
  type        = string
  default     = "../../../build/syft-layer.zip"
  description = "Path of syft-layer.zip, built by scripts/build/build_syft_layer.py in the same CI job (SB-SBOM-3)."
}
variable "syft_layer_sha256" {
  type        = string
  description = "Hex SHA-256 of syft-layer.zip, printed by the build script. CI passes it as TF_VAR_syft_layer_sha256 (SB-CI-2)."
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.syft_layer_sha256))
    error_message = "Give 64 lower-case hex characters."
  }
}
variable "sources_contact" {
  type        = string
  default     = "https://github.com/olajaido/graveyard"
  description = "Contact in the User-Agent of the source clients (SB-CFG-1). A public project URL by default; not a secret."
}
variable "cors_allowed_origins" {
  type        = list(string)
  default     = ["https://dev.lastrites.dev", "http://localhost:5173"]
  description = "Browser origins the API allows (EDGE-CORS-1): the dev site, and the local web app (npm run dev serves on port 5173, ui-core UI-CORS-1). The first entry must be https://<site host>; a root test checks it. Methods GET, POST and OPTIONS; header content-type."
}
variable "domain_name" {
  type        = string
  default     = "lastrites.dev"
  description = "Public domain of the site and the API (spec infra-edge). Prod serves the domain itself, other envs serve <env>.<domain>. The hosted zone for it already exists and is not managed here."
  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.domain_name))
    error_message = "Give a lower-case domain name with no scheme, no wildcard and no trailing dot."
  }
}
variable "route53_zone_id" {
  type        = string
  description = "ID of the existing public hosted zone for domain_name. Not a secret, but supplied at run time like the account ID: TF_VAR_route53_zone_id from the repository variable ROUTE53_ZONE_ID in CI, the git-ignored terraform.tfvars locally (EDGE-DNS-1)."
  validation {
    condition     = can(regex("^Z[A-Z0-9]{3,40}$", var.route53_zone_id))
    error_message = "A hosted zone ID starts with Z and holds only capital letters and digits."
  }
}
variable "enable_waf" {
  type        = bool
  default     = null
  description = "Whether the env has the Edge ACL (WAF). null means the env named prod only (decision R7); true gives any env the ACL, false removes it."
}
variable "price_class" {
  type        = string
  default     = "PriceClass_100"
  description = "CloudFront price class of both distributions (EDGE-COST-1)."
  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)
    error_message = "Use PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}
variable "scan_rate_limit" {
  type        = number
  default     = 20
  description = "Most POST /v1/scans requests one IP may make in 5 minutes before the Edge ACL blocks it with 429 (EDGE-WAF-2). WAF accepts 10 or more."
}
