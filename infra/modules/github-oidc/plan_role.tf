locals {
  # Trust (INF-OIDC-2, INF-OIDC-3): StringEquals on audience and subject, each subject listed in full.
  trust_plan = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.arn.oidc }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.oidc_host}:aud" = "sts.amazonaws.com"
          "${local.oidc_host}:sub" = [
            "repo:${local.repo}:pull_request",
            "repo:${local.repo}:ref:refs/heads/main",
          ]
        }
      }
    }]
  })
}

resource "aws_iam_role" "plan" {
  name                 = "graveyard-plan"
  path                 = var.ci_path
  description          = "Read-only role for terraform plan in CI (pull requests and main). Writes only plans/* and the env lock keys."
  assume_role_policy   = local.trust_plan
  max_session_duration = 3600

  # An empty list when the provider is not created here.
  depends_on = [aws_iam_openid_connect_provider.github]
}

resource "aws_iam_role_policy_attachment" "plan" {
  for_each = toset(concat(keys(local.plan_policies), keys(local.plan_read_policies)))

  role       = aws_iam_role.plan.name
  policy_arn = aws_iam_policy.ci[each.key].arn
}
