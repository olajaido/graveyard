config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.50.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

# Provider default_tags are the only tag source (INF-TAG-1); this rule checks every taggable resource gets all six.
rule "aws_resource_missing_tags" {
  enabled = true
  tags    = ["Project", "Env", "Owner", "ManagedBy", "CostCentre", "Repo"]
}
