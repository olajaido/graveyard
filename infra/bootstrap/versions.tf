terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.73.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.9.1"
    }
  }

  # The bucket and the KMS key ARN are not written here: they identify the account and are supplied by
  # partial configuration (INF-STATE-7): `-backend-config=backend.hcl` locally, run-time values in CI.
  # The first apply uses a git-ignored local_backend_override.tf with backend "local" (INF-BOOT-2).
  backend "s3" {
    key          = "bootstrap/terraform.tfstate"
    region       = "eu-west-2"
    use_lockfile = true
    encrypt      = true
  }
}
