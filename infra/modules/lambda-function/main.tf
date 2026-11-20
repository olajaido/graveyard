# One Lambda function with its own role, log group, a published version and the live alias (SB-INF-3, SB-INF-4).
# Python 3.12 on arm64, X-Ray on. The role carries the env's workload boundary and an inline policy built with
# jsonencode (no aws_iam_policy_document, terraform.md).
locals {
  role_path = "/graveyard-${var.env}/"
  log_group = "/aws/lambda/${var.name}"
  log_arn   = "arn:${var.partition}:logs:${var.region}:${var.account_id}:log-group:${local.log_group}"
  base_statements = [
    {
      Sid      = "Logs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = ["${local.log_arn}:*"]
    },
    # Exceptions E1 and E2 (approved 18 Nov 2026): X-Ray has no resource-level permissions.
    {
      Sid      = "XRay"
      Effect   = "Allow"
      Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
      Resource = "*"
    },
  ]
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = concat(local.base_statements, var.statements)
  })
  assume_role = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}
resource "aws_cloudwatch_log_group" "this" {
  name              = local.log_group
  retention_in_days = var.log_retention_days
  # No customer-managed key: log delivery of the service would need its own key grants. The logs hold no secrets (SB-OBS-2).
  # checkov:skip=CKV_AWS_158:Lambda logs hold no secrets or file contents (SB-OBS-2); a CMK needs a key policy for the logs service.
  # checkov:skip=CKV_AWS_338:Retention is a variable; the default of 30 days is intended (SB-INF-3).
}
resource "aws_iam_role" "this" {
  name                 = var.name
  path                 = local.role_path
  permissions_boundary = var.boundary_arn
  assume_role_policy   = local.assume_role
}
resource "aws_iam_role_policy" "this" {
  name   = var.name
  role   = aws_iam_role.this.name
  policy = local.policy
}
resource "aws_lambda_function" "this" {
  function_name                  = var.name
  role                           = aws_iam_role.this.arn
  handler                        = var.handler
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  filename                       = var.filename
  source_code_hash               = filebase64sha256(var.filename)
  memory_size                    = var.memory_size
  timeout                        = var.timeout
  publish                        = true
  reserved_concurrent_executions = var.reserved_concurrency
  layers                         = var.layers
  tracing_config {
    mode = "Active"
  }
  environment {
    variables = var.environment
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.this.name
  }
  depends_on = [aws_iam_role_policy.this]
  # checkov:skip=CKV_AWS_117:No VPC by design (tech.md architecture rules).
  # checkov:skip=CKV_AWS_116:No dead-letter queue: Step Functions and API Gateway call the function synchronously and get the error.
  # checkov:skip=CKV_AWS_173:Environment variables hold resource names only (SB-CFG-3).
  # checkov:skip=CKV_AWS_272:Code signing is not used for the hackathon build; the zip hash is pinned in the plan (SB-CI-2).
  lifecycle {
    precondition {
      condition     = filesha256(var.filename) == var.zip_sha256
      error_message = "lambda.zip differs from the hash the plan was made with (SB-CI-2). Rebuild it with scripts/build/build_lambda_zip.py."
    }
  }
}
resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.this.function_name
  function_version = aws_lambda_function.this.version
}
