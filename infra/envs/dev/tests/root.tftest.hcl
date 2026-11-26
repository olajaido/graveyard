# Offline plan of the whole dev root with a mock provider: the module calls fit together (scan-backend, SB-INF-1, SB-INF-2).
mock_provider "aws" {}
mock_provider "aws" {
  alias = "us_east_1"
}
mock_provider "random" {}
override_resource {
  target          = module.data.aws_kms_key.app
  override_during = plan
  values = {
    arn    = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
    key_id = "00000000-0000-0000-0000-000000000000"
  }
}
override_resource {
  target          = module.data.aws_s3_bucket.artefacts
  override_during = plan
  values = {
    arn = "arn:aws:s3:::graveyard-dev-artefacts-20260101"
    id  = "graveyard-dev-artefacts-20260101"
  }
}
override_resource {
  target          = module.data.aws_dynamodb_table.data
  override_during = plan
  values = {
    arn = "arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-data"
  }
}
override_resource {
  target          = module.github_app.aws_secretsmanager_secret.reader
  override_during = plan
  values = {
    arn = "arn:aws:secretsmanager:eu-west-2:123456789012:secret:graveyard/dev/github/reader-AbCdEf"
  }
}
override_resource {
  target          = module.api.aws_apigatewayv2_api.http
  override_during = plan
  values = {
    id            = "abc123"
    execution_arn = "arn:aws:execute-api:eu-west-2:123456789012:abc123"
    api_endpoint  = "https://abc123.execute-api.eu-west-2.amazonaws.com"
  }
}
override_resource {
  target          = module.observability.aws_sns_topic.alerts
  override_during = plan
  values          = { arn = "arn:aws:sns:eu-west-2:123456789012:graveyard-dev-alerts" }
}
override_resource {
  target          = module.edge_cert.aws_acm_certificate.this
  override_during = plan
  values = {
    arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    domain_validation_options = [
      { domain_name = "dev.lastrites.dev", resource_record_name = "_a1.dev.lastrites.dev.", resource_record_type = "CNAME", resource_record_value = "_v1.acm-validations.aws." },
      { domain_name = "api.dev.lastrites.dev", resource_record_name = "_a2.api.dev.lastrites.dev.", resource_record_type = "CNAME", resource_record_value = "_v2.acm-validations.aws." },
    ]
  }
}
override_resource {
  target          = module.edge_site.random_id.suffix
  override_during = plan
  values          = { hex = "0a1b2c3d" }
}
override_resource {
  target          = module.edge_site.aws_s3_bucket.site
  override_during = plan
  values = {
    id                          = "graveyard-dev-site-0a1b2c3d"
    arn                         = "arn:aws:s3:::graveyard-dev-site-0a1b2c3d"
    bucket_regional_domain_name = "graveyard-dev-site-0a1b2c3d.s3.eu-west-2.amazonaws.com"
  }
}
override_resource {
  target          = module.edge_site.aws_cloudfront_distribution.site
  override_during = plan
  values = {
    id             = "E2EXAMPLE12345"
    arn            = "arn:aws:cloudfront::123456789012:distribution/E2EXAMPLE12345"
    domain_name    = "d111111abcdef8.cloudfront.net"
    hosted_zone_id = "Z2FDTNDATAQYW2"
  }
}
override_resource {
  target          = module.edge_api.aws_cloudfront_distribution.api
  override_during = plan
  values = {
    id             = "E4EXAMPLE67890"
    arn            = "arn:aws:cloudfront::123456789012:distribution/E4EXAMPLE67890"
    domain_name    = "d222222abcdef8.cloudfront.net"
    hosted_zone_id = "Z2FDTNDATAQYW2"
  }
}
override_resource {
  target          = module.edge_alarms.aws_sns_topic.edge
  override_during = plan
  values          = { arn = "arn:aws:sns:us-east-1:123456789012:graveyard-dev-edge-alerts" }
}
variables {
  allowed_account_ids = ["123456789012"]
  route53_zone_id     = "Z0123456789ABCDEFGHIJ"
  lambda_zip_path     = "../../modules/lambda-function/tests/fixtures/lambda.zip"
  lambda_zip_sha256   = "9940df3df16c98c88fcc166e2fe9bd3fb6c2dc3c4e7b36254445ea3cae987a5d"
  syft_layer_zip_path = "../../modules/lambda-function/tests/fixtures/lambda.zip"
  syft_layer_sha256   = "9940df3df16c98c88fcc166e2fe9bd3fb6c2dc3c4e7b36254445ea3cae987a5d"
}
run "the_root_wires_the_modules_with_the_env_prefix" {
  command = plan
  assert {
    condition     = output.name_prefix == "graveyard-dev" && output.table_name == "graveyard-dev-data" && output.state_machine_name == "graveyard-dev-scan"
    error_message = "Every name starts with graveyard-<env>-."
  }
  assert {
    condition     = output.reader_secret_name == "graveyard/dev/github/reader"
    error_message = "The reader secret path."
  }
  assert {
    condition     = module.workflow.state_machine_alias_arn == "arn:aws:states:eu-west-2:123456789012:stateMachine:graveyard-dev-scan:live"
    error_message = "The API starts the live alias of the scan state machine."
  }
}
run "every_role_carries_the_env_boundary_and_the_workload_path" {
  command = plan
  assert {
    condition     = module.api.function_name == "graveyard-dev-api" && length(module.workflow.function_names) == 7
    error_message = "One api function and seven task functions."
  }
  assert {
    condition     = module.workflow.sfn_role_boundary_arn == "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary"
    error_message = "The boundary ARN is built from the allowed account and the env prefix."
  }
}
run "the_total_reserved_concurrency_is_about_fifty" {
  command = plan
  assert {
    condition     = sum([for k, f in module.workflow.function_settings : f.reserved_concurrency]) + 8 == 50
    error_message = "42 for the task functions plus 8 for the api: about 50 per env (the review of 19 Nov 2026)."
  }
}
run "the_api_stage_has_no_access_logs_in_this_root" {
  command = plan
  assert {
    condition     = module.api.access_log_group_name == null
    error_message = "Access logging stays off until the security review (H11); the env roots use the module default."
  }
}
run "the_dev_api_allows_the_dev_site_and_the_local_web_app_only" {
  command = plan
  assert {
    condition     = module.api.cors_allow_origins == toset(["https://dev.lastrites.dev", "http://localhost:5173"])
    error_message = "Dev allows the dev site and the local web app (EDGE-CORS-1, ui-core UI-CORS-1)."
  }
  assert {
    condition     = var.cors_allowed_origins[0] == "https://${local.site_host}"
    error_message = "The first CORS origin must be the site host."
  }
}
run "the_hostnames_are_derived_from_the_domain_and_the_env" {
  command = plan
  assert {
    condition     = local.site_host == "dev.lastrites.dev" && local.api_host == "api.dev.lastrites.dev" && local.hostnames == ["dev.lastrites.dev", "api.dev.lastrites.dev"]
    error_message = "Dev: dev.lastrites.dev and api.dev.lastrites.dev, no www."
  }
  assert {
    condition     = output.site_url == "https://dev.lastrites.dev" && output.api_public_url == "https://api.dev.lastrites.dev"
    error_message = "The public URLs."
  }
}
run "dev_has_no_web_acl_by_default" {
  command = plan
  assert {
    condition     = output.web_acl_arn == null && module.edge_site.web_acl_id == null && module.edge_api.web_acl_id == null && length(module.edge_waf) == 0
    error_message = "Dev has no Edge ACL (decision R7)."
  }
}
run "dev_can_opt_in_to_the_web_acl" {
  command = plan
  variables {
    enable_waf = true
  }
  override_resource {
    target          = module.edge_waf[0].aws_wafv2_web_acl.this
    override_during = plan
    values          = { arn = "arn:aws:wafv2:us-east-1:123456789012:global/webacl/graveyard-dev-edge/11111111-1111-1111-1111-111111111111" }
  }
  assert {
    condition     = length(module.edge_waf) == 1 && module.edge_site.web_acl_id == output.web_acl_arn && module.edge_api.web_acl_id == output.web_acl_arn && output.web_acl_arn == "arn:aws:wafv2:us-east-1:123456789012:global/webacl/graveyard-dev-edge/11111111-1111-1111-1111-111111111111"
    error_message = "enable_waf = true gives dev the ACL, named graveyard-dev-edge."
  }
}
run "the_certificate_reaches_both_distributions_and_the_csp_names_the_api_host" {
  command = plan
  assert {
    condition     = module.edge_site.csp == "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://api.dev.lastrites.dev; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests"
    error_message = "The CSP names the dev API host."
  }
  assert {
    condition     = module.edge_cert.certificate_arn == "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000" && output.site_bucket_name == "graveyard-dev-site-0a1b2c3d"
    error_message = "The certificate and the bucket name come through."
  }
}
run "the_alarms_and_the_topic_are_in_the_env_and_the_api_is_the_origin" {
  command = plan
  assert {
    condition     = output.edge_alerts_topic_arn == "arn:aws:sns:us-east-1:123456789012:graveyard-dev-edge-alerts" && toset(module.edge_alarms.alarm_names) == toset(["graveyard-dev-cdn-site-5xx", "graveyard-dev-cdn-api-5xx"])
    error_message = "The edge topic and the two alarm names."
  }
}
