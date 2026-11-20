locals {
  # One trust policy per env: exactly one subject, the GitHub environment of the same name (INF-OIDC-4).
  trust_apply = { for e in local.env_list : e => jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.arn.oidc }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.oidc_host}:aud" = "sts.amazonaws.com"
          "${local.oidc_host}:sub" = "repo:${local.repo}:environment:${e}"
        }
      }
    }]
  }) }

  # Policy documents per env and short name. Policy names are graveyard-<env>-apply-<short name>.
  apply_policy_docs = { for e in local.env_list : e => merge(local.apply_core_docs[e], local.apply_service_docs[e]) }

  apply_policies = merge([
    for e in local.env_list : { for n, doc in local.apply_policy_docs[e] : "graveyard-${e}-apply-${n}" => doc }
  ]...)

  apply_attachments = merge([
    for e in local.env_list : { for n in keys(local.apply_policy_docs[e]) : "${e}/${n}" => { env = e, policy = "graveyard-${e}-apply-${n}" } }
  ]...)
}

resource "aws_iam_role" "apply" {
  for_each = toset(local.env_list)

  name                 = "graveyard-${each.key}-apply"
  path                 = var.ci_path
  description          = "Applies the ${each.key} Terraform root from the GitHub environment ${each.key}. Limited to graveyard-${each.key} names and the Project tag."
  assume_role_policy   = local.trust_apply[each.key]
  max_session_duration = 3600

  depends_on = [aws_iam_openid_connect_provider.github]
}

resource "aws_iam_role_policy_attachment" "apply" {
  for_each = local.apply_attachments

  role       = aws_iam_role.apply[each.value.env].name
  policy_arn = aws_iam_policy.ci[each.value.policy].arn
}
