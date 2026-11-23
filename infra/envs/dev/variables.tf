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
  default     = ["http://localhost:5173"]
  description = "Browser origins the API allows. Dev only: the local web app (npm run dev serves on port 5173), see ui-core UI-CORS-1. Methods GET, POST and OPTIONS; header content-type."
}
