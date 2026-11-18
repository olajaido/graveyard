# Shared locals. Every ARN is built from names, the partition and the account ID input (INF-POL-1);
# this module declares no data source. The OIDC provider ARN is always this string: the module never
# looks the provider up and never manages one that another project owns (INF-OIDC-10).
locals {
  p             = var.partition
  a             = var.account_id
  r             = var.region
  global_region = "us-east-1"
  oidc_host     = "token.actions.githubusercontent.com"
  repo          = "${var.repo_owner}/${var.repo_name}"
  env_list      = sort(tolist(var.envs))

  # The Project tag, written exactly as in the PRD section 14.1 tag set (case-sensitive).
  tag_project_key   = "Project"
  tag_project_value = "graveyard"

  arn = {
    oidc         = "arn:${local.p}:iam::${local.a}:oidc-provider/${local.oidc_host}"
    state_bucket = "arn:${local.p}:s3:::${var.state_bucket_name}"
    state_key    = var.state_kms_key_arn
    ci_roles     = "arn:${local.p}:iam::${local.a}:role${var.ci_path}"
    ci_policies  = "arn:${local.p}:iam::${local.a}:policy${var.ci_path}"
  }

  boundary_arn = { for e in local.env_list : e => "${local.arn.ci_policies}graveyard-${e}-boundary" }
  state_object = { for e in local.env_list : e => "${local.arn.state_bucket}/envs/${e}/terraform.tfstate" }
  lock_object  = { for e in local.env_list : e => "${local.arn.state_bucket}/envs/${e}/terraform.tfstate.tflock" }

  # Denied for every CI role and boundary (INF-REG-2): nothing outside eu-west-2, except global
  # services; CloudFront-scope services may also use us-east-1.
  region_deny = [
    {
      Sid       = "DenyOutsideRegion"
      Effect    = "Deny"
      NotAction = ["iam:*", "sts:*", "cloudfront:*", "wafv2:*", "acm:*", "budgets:*", "ce:*", "s3:ListAllMyBuckets", "s3:GetBucketLocation"]
      Resource  = "*"
      Condition = { StringNotEquals = { "aws:RequestedRegion" = local.r } }
    },
    {
      Sid       = "DenyGlobalOutsideUsEast1"
      Effect    = "Deny"
      Action    = ["cloudfront:*", "wafv2:*", "acm:*"]
      Resource  = "*"
      Condition = { StringNotEquals = { "aws:RequestedRegion" = [local.r, local.global_region] } }
    },
  ]

  # All managed policies of the CI roles, by name. Later parts of this module add to the merge.
  managed_policies = merge(local.plan_policies, local.plan_read_policies, local.apply_policies, local.boundary_policies)
}

# Created only when asked (SA3). With the default there is no provider resource at all, so a plan
# cannot adopt or change the existing one.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "ci" {
  for_each = local.managed_policies

  name        = each.key
  path        = var.ci_path
  description = "Graveyard CI policy ${each.key}. Managed by the bootstrap root."
  policy      = each.value
}
