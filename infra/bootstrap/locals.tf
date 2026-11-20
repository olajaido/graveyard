locals {
  env = "shared"

  # The Project tag is defined once. The budget filter, the anomaly monitor and default_tags all read it,
  # so they cannot drift apart (INF-COST-6). Written exactly as in the PRD section 14.1 tag set.
  project_tag_key   = "Project"
  project_tag_value = "graveyard"

  tags = merge(
    { (local.project_tag_key) = local.project_tag_value },
    {
      Env        = local.env
      Owner      = "olajide"
      ManagedBy  = "terraform"
      CostCentre = "kiroween-2026"
      Repo       = "github.com/olajaido/graveyard"
    },
  )
}
