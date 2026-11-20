# Offline tests for the github-app module (SB-CFG-1, SB-CFG-2, SB-SEC-3).
mock_provider "aws" {}
variables {
  env         = "dev"
  kms_key_arn = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
}
run "the_secret_is_an_empty_container_under_the_env_path" {
  command = plan
  assert {
    condition     = aws_secretsmanager_secret.reader.name == "graveyard/dev/github/reader" && aws_secretsmanager_secret.reader.recovery_window_in_days == 7
    error_message = "graveyard/<env>/github/reader with a 7 day recovery window."
  }
  assert {
    condition     = aws_secretsmanager_secret.reader.kms_key_id == "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
    error_message = "Encrypted with the app CMK."
  }
}
run "the_identifiers_start_unset_under_the_env_path" {
  command = plan
  assert {
    condition     = { for k, p in aws_ssm_parameter.identifier : p.name => p.value } == { "/graveyard/dev/github/reader/app-id" = "UNSET", "/graveyard/dev/github/reader/installation-id" = "UNSET" }
    error_message = "Two parameters, both UNSET."
  }
}
run "prod_follows_the_env" {
  command = plan
  variables {
    env = "prod"
  }
  assert {
    condition     = aws_secretsmanager_secret.reader.name == "graveyard/prod/github/reader"
    error_message = "graveyard/prod/github/reader."
  }
}
