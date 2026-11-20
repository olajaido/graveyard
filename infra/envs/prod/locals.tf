locals {
  env = "prod"

  # The PRD section 14.1 tag set, written once per root (INF-TAG-1, INF-TAG-2).
  tags = {
    Project    = "graveyard"
    Env        = local.env
    Owner      = "olajide"
    ManagedBy  = "terraform"
    CostCentre = "kiroween-2026"
    Repo       = "github.com/olajaido/graveyard"
  }

  # Every named resource of this root starts with this prefix (INF-NAME-1).
  name_prefix = "graveyard-${local.env}"
}
locals {
  account_id = var.allowed_account_ids[0]
  partition  = "aws"
  # The env's workload boundary, made by the bootstrap root (INF-APPLY-7). Every workload role carries it (INF-APPLY-4).
  boundary_arn = "arn:${local.partition}:iam::${local.account_id}:policy/graveyard-ci/${local.name_prefix}-boundary"
}
