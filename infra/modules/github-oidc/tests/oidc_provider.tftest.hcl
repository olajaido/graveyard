# The OIDC provider is reused from the shared account by default (SA3, INF-OIDC-1, INF-OIDC-10).
# Both settings of create_oidc_provider are covered.

mock_provider "aws" {}

variables {
  account_id        = "123456789012"
  partition         = "aws"
  repo_owner        = "olajaido"
  repo_name         = "graveyard"
  repo_owner_id     = "102736714"
  repo_id           = "1443508961"
  state_bucket_name = "graveyard-tfstate-abcd1234"
  state_kms_key_arn = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
}

run "default_creates_no_provider_and_builds_the_arn" {
  command = plan

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0
    error_message = "With create_oidc_provider = false (the default) no provider resource may exist."
  }

  assert {
    condition     = jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Principal.Federated == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    error_message = "The trust principal must be the ARN built from account_id and partition."
  }

  assert {
    condition     = output.oidc_provider_arn == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    error_message = "The oidc_provider_arn output must be the built ARN."
  }
}

run "explicit_false_behaves_like_the_default" {
  command = plan

  variables {
    create_oidc_provider = false
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0
    error_message = "An explicit false must create no provider."
  }
}

run "true_creates_exactly_one_provider_for_github" {
  command = plan

  variables {
    create_oidc_provider = true
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 1
    error_message = "With create_oidc_provider = true exactly one provider must be created."
  }

  assert {
    condition     = aws_iam_openid_connect_provider.github[0].url == "https://token.actions.githubusercontent.com"
    error_message = "The provider URL must be the GitHub Actions issuer."
  }

  assert {
    condition     = toset(aws_iam_openid_connect_provider.github[0].client_id_list) == toset(["sts.amazonaws.com"])
    error_message = "The only client ID (audience) must be sts.amazonaws.com."
  }

  assert {
    condition     = output.oidc_provider_arn == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    error_message = "The output must be the same string whether the provider is created or reused."
  }

  assert {
    condition     = jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Principal.Federated == output.oidc_provider_arn
    error_message = "The trust principal must be the same ARN in both settings."
  }
}

run "the_arn_is_built_from_the_partition_input" {
  command = plan

  variables {
    partition = "aws-us-gov"
  }

  assert {
    condition     = output.oidc_provider_arn == "arn:aws-us-gov:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    error_message = "The partition must come from the input."
  }
}

run "the_arn_is_built_from_the_account_input" {
  command = plan

  variables {
    account_id = format("%012d", 7) # built, so no second 12-digit literal is in the repository
  }

  assert {
    condition     = output.oidc_provider_arn == "arn:aws:iam::${format("%012d", 7)}:oidc-provider/token.actions.githubusercontent.com"
    error_message = "The account ID must come from the input."
  }
}
