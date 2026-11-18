# The dev root is intentionally empty. Later specs add module calls here: infra-serverless (api, workflow,
# data), infra-edge (CloudFront, WAF) and observability. Until then CI plans it and shows "No changes", so the
# plan and deploy path is exercised from day one.
#
# infra-edge will also add the us-east-1 provider alias that CloudFront certificates need (INF-REG-3):
#
#   provider "aws" {
#     alias               = "us_east_1"
#     region              = "us-east-1"
#     allowed_account_ids = var.allowed_account_ids
#     default_tags { tags = local.tags }
#   }
#
# This root declares no resource (INF-LAY-2): resources belong in modules under infra/modules/.
