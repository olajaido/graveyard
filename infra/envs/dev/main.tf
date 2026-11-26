# The scan backend (spec scan-backend): data, the GitHub App secret container, the workflow, the API and the alarms.
# The roots call the same modules and differ only in the env name (INF-LAY-4). This root declares no resource and no
# data source (INF-LAY-2): the account ID is the one allowed account (INF-CFG-2), and the partition is aws.
# The edge (spec infra-edge) is at the end: certificate, Edge ACL (prod only by default), site, API distribution, alarms.
module "data" {
  source = "../../modules/data"

  name_prefix = local.name_prefix
  env         = local.env
  account_id  = local.account_id
  partition   = local.partition
  region      = var.region
  contact     = var.sources_contact
}
module "github_app" {
  source = "../../modules/github-app"

  env         = local.env
  kms_key_arn = module.data.kms_key_arn
}
module "workflow" {
  source = "../../modules/workflow"

  name_prefix               = local.name_prefix
  env                       = local.env
  account_id                = local.account_id
  partition                 = local.partition
  region                    = var.region
  boundary_arn              = local.boundary_arn
  table_name                = module.data.table_name
  table_arn                 = module.data.table_arn
  bucket_name               = module.data.bucket_name
  bucket_arn                = module.data.bucket_arn
  kms_key_arn               = module.data.kms_key_arn
  reader_secret_arn         = module.github_app.secret_arn
  reader_secret_name        = module.github_app.secret_name
  ssm_parameter_arn_pattern = module.data.ssm_parameter_arn_pattern
  lambda_zip_path           = var.lambda_zip_path
  lambda_zip_sha256         = var.lambda_zip_sha256
  syft_layer_zip_path       = var.syft_layer_zip_path
  syft_layer_sha256         = var.syft_layer_sha256
}
module "api" {
  source = "../../modules/api"

  name_prefix               = local.name_prefix
  env                       = local.env
  account_id                = local.account_id
  partition                 = local.partition
  region                    = var.region
  boundary_arn              = local.boundary_arn
  table_name                = module.data.table_name
  table_arn                 = module.data.table_arn
  table_index_arn           = module.data.table_index_arn
  kms_key_arn               = module.data.kms_key_arn
  ssm_parameter_arn_pattern = module.data.ssm_parameter_arn_pattern
  state_machine_arn         = module.workflow.state_machine_arn
  state_machine_alias_arn   = module.workflow.state_machine_alias_arn
  lambda_zip_path           = var.lambda_zip_path
  lambda_zip_sha256         = var.lambda_zip_sha256
  cors_allowed_origins      = var.cors_allowed_origins
}
module "observability" {
  source = "../../modules/observability"

  name_prefix        = local.name_prefix
  env                = local.env
  account_id         = local.account_id
  partition          = local.partition
  region             = var.region
  function_names     = concat(module.workflow.function_names, [module.api.function_name])
  api_function_name  = module.api.function_name
  state_machine_name = module.workflow.state_machine_name
  api_id             = module.api.api_id
  table_name         = module.data.table_name
}
# ACM for CloudFront must be in us-east-1, and Route 53 is global, so the one provider of this module is the us-east-1 one.
module "edge_cert" {
  source = "../../modules/edge-cert"
  providers = {
    aws = aws.us_east_1
  }
  domain_names = local.hostnames
  zone_id      = var.route53_zone_id
}
# The Edge ACL exists in prod only by default (decision R7). It is a CLOUDFRONT-scope ACL, so it is made in us-east-1.
module "edge_waf" {
  source = "../../modules/edge-waf"
  count  = local.enable_waf ? 1 : 0
  providers = {
    aws = aws.us_east_1
  }
  name_prefix     = local.name_prefix
  scan_rate_limit = var.scan_rate_limit
}
module "edge_site" {
  source          = "../../modules/edge-site"
  name_prefix     = local.name_prefix
  site_host       = local.site_host
  redirect_www    = local.redirect_www
  api_host        = local.api_host
  certificate_arn = module.edge_cert.certificate_arn
  web_acl_arn     = one(module.edge_waf[*].web_acl_arn)
  zone_id         = var.route53_zone_id
  price_class     = var.price_class
}
module "edge_api" {
  source          = "../../modules/edge-api"
  name_prefix     = local.name_prefix
  api_host        = local.api_host
  api_endpoint    = module.api.api_url
  certificate_arn = module.edge_cert.certificate_arn
  web_acl_arn     = one(module.edge_waf[*].web_acl_arn)
  zone_id         = var.route53_zone_id
  price_class     = var.price_class
}
# CloudFront publishes its metrics in us-east-1 only, so the alarms and their topic are made there (R1).
module "edge_alarms" {
  source = "../../modules/edge-alarms"
  providers = {
    aws = aws.us_east_1
  }
  name_prefix          = local.name_prefix
  site_distribution_id = module.edge_site.distribution_id
  api_distribution_id  = module.edge_api.distribution_id
}
