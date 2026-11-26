# Shared locals. Every ARN is built from names, the partition and the account ID input (INF-POL-1);
# this module declares no data source. The OIDC provider ARN is always this string: the module never
# looks the provider up and never manages one that another project owns (INF-OIDC-10).
locals {
  p             = var.partition
  a             = var.account_id
  r             = var.region
  global_region = "us-east-1"
  oidc_host     = "token.actions.githubusercontent.com"
  # GitHub's immutable subject (the repository's OIDC customization has use_immutable_subject = true, found at the
  # first CI run, T24): "repo:<owner>@<owner id>/<repo>@<repo id>:...". The IDs close repository-name reuse: a deleted
  # and recreated repository of the same name has other IDs, so it cannot assume the roles. The old
  # "repo:<owner>/<repo>:..." form is never emitted by such a repository and is not trusted.
  repo     = "${var.repo_owner}@${var.repo_owner_id}/${var.repo_name}@${var.repo_id}"
  env_list = sort(tolist(var.envs))

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

  # Exception E11 (infra-edge, INF-REG-2): the only actions the CI roles may use in us-east-1 besides the global services above.
  # Route 53 is a global service whose calls are reported as us-east-1. CloudFront publishes its metrics in us-east-1 only, so the
  # CloudFront 5xx alarms and their SNS topic live there. Each action is still allowed only on the ARNs of
  # policies_apply_edge_extra.tf (the zone, and graveyard-<env>-* alarms and topics). The boundaries do not use this list.
  region_us_east_1_actions = concat(
    ["route53:ChangeResourceRecordSets", "route53:GetChange", "route53:GetHostedZone", "route53:ListResourceRecordSets"],
    local.act.edge_alarm_write, local.act.edge_alarm_read, ["cloudwatch:DescribeAlarms"],
    local.act.edge_topic_write, local.act.edge_topic_read,
  )
  # The region deny of the plan guard and the apply guards: region_deny plus E11. region_deny itself stays as it is, because the
  # workload boundaries are built from it and sit 60 characters under the 6,144 limit (infra-edge R9).
  # Both statements apply to direct calls only (aws:ViaAWSService = false). When CloudFront creates a distribution it validates the
  # certificate with a forward access session, a call that AWS makes in the caller's name from another region (E11 amendment,
  # 26 Nov 2026): the same CreateDistribution succeeded for an admin principal and failed with InvalidViewerCertificate for
  # graveyard-dev-apply, which had only this deny and no CloudTrail denial to show for it. A direct call outside the allowed
  # regions is still denied. The boundaries use region_deny and are unchanged.
  region_deny_ci = [
    merge(local.region_deny[0], {
      NotAction = concat(local.region_deny[0].NotAction, local.region_us_east_1_actions)
      Condition = merge(local.region_deny[0].Condition, { Bool = { "aws:ViaAWSService" = "false" } })
    }),
    merge(local.region_deny[1], {
      Action    = concat(local.region_deny[1].Action, local.region_us_east_1_actions)
      Condition = merge(local.region_deny[1].Condition, { Bool = { "aws:ViaAWSService" = "false" } })
    }),
  ]
  # Host names of the edge, by env (infra-edge design 6): the site host is the domain in prod and <env>.<domain> otherwise.
  edge_site_host = { for e in local.env_list : e => e == "prod" ? var.edge_domain_name : "${e}.${var.edge_domain_name}" }
  # Record names as Route 53 normalises them (lower-case, no trailing dot). "_*.<site host>" is for the ACM validation CNAMEs.
  edge_record_names = { for e in local.env_list : e => concat(
    [local.edge_site_host[e], "api.${local.edge_site_host[e]}", "_*.${local.edge_site_host[e]}"],
    e == "prod" ? ["www.${var.edge_domain_name}"] : [],
  ) }
  arn_zone = "arn:${local.p}:route53:::hostedzone/${var.route53_zone_id}"
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
