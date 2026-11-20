# The scan workflow (SB-WF-1 to SB-WF-6, SB-INF-3 to SB-INF-5): the seven task functions, the Syft layer, the
# Standard state machine with its Distributed Map, its role, log group and live alias.
#
# ARNs of the functions and of the state machine are built from names, not read from the resources. That keeps the
# state machine definition and the policies known at plan time (so tests can read them) and avoids cycles between
# the state machine role and the state machine. The state machine depends on the functions explicitly.
locals {
  p            = var.partition
  region       = var.region
  account      = var.account_id
  machine_name = "${var.name_prefix}-scan"
  machine_arn  = "arn:${local.p}:states:${local.region}:${local.account}:stateMachine:${local.machine_name}"
  alias_arn    = "${local.machine_arn}:live"
  role_path    = "/graveyard-${var.env}/"
  scans        = "${var.bucket_arn}/scans/*"
  alias_arns   = { for k, _ in var.functions : k => "arn:${local.p}:lambda:${local.region}:${local.account}:function:${var.name_prefix}-${k}:live" }

  common_env = {
    GRAVEYARD_ENV                = var.env
    TABLE_NAME                   = var.table_name
    BUCKET_NAME                  = var.bucket_name
    READER_SECRET_ID             = var.reader_secret_name
    POWERTOOLS_SERVICE_NAME      = "graveyard"
    POWERTOOLS_METRICS_NAMESPACE = "Graveyard/${var.env}"
    LOG_LEVEL                    = "INFO"
  }

  st = {
    ssm        = { Sid = "Parameters", Effect = "Allow", Action = ["ssm:GetParameter", "ssm:GetParameters"], Resource = [var.ssm_parameter_arn_pattern] }
    secret     = { Sid = "ReaderSecret", Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.reader_secret_arn] }
    key        = { Sid = "Key", Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = [var.kms_key_arn] }
    s3_get     = { Sid = "ArtefactsRead", Effect = "Allow", Action = ["s3:GetObject"], Resource = [local.scans] }
    s3_put     = { Sid = "ArtefactsWrite", Effect = "Allow", Action = ["s3:PutObject"], Resource = [local.scans] }
    ddb_update = { Sid = "TableUpdate", Effect = "Allow", Action = ["dynamodb:UpdateItem"], Resource = [var.table_arn] }
    ddb_cache  = { Sid = "TableCache", Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:PutItem"], Resource = [var.table_arn] }
    ddb_nodes  = { Sid = "TableNodes", Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:PutItem", "dynamodb:BatchWriteItem", "dynamodb:UpdateItem"], Resource = [var.table_arn] }
    ddb_meta   = { Sid = "TableMeta", Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:UpdateItem"], Resource = [var.table_arn] }
  }

  # The statements of SB-INF-5, per function. The handlers are workflow.<name>.handler.
  tasks = {
    validate = [local.st.ssm, local.st.ddb_update, local.st.key]
    fetch    = [local.st.secret, local.st.ssm, local.st.ddb_update, local.st.s3_put, local.st.key]
    syft     = [local.st.s3_get, local.st.s3_put, local.st.key]
    graph    = [local.st.s3_get, local.st.s3_put, local.st.ddb_update, local.st.key]
    autopsy  = [local.st.secret, local.st.ssm, local.st.ddb_cache, local.st.key]
    classify = [local.st.s3_get, local.st.ddb_nodes, local.st.key]
    finalise = [local.st.ddb_meta, local.st.key]
  }

  # ---- the state machine (SB-WF-1 to SB-WF-3, SB-WF-5) -------------------------------------------------------------
  lambda_retry = {
    ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2
    JitterStrategy  = "FULL"
  }
  rate_limit_retry = {
    ErrorEquals     = ["GITHUB_RATE_LIMITED"]
    IntervalSeconds = 30
    MaxAttempts     = 1
    BackoffRate     = 1
  }
  catch_all   = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "HandleError" }]
  user_errors = ["INVALID_INPUT", "REPO_NOT_FOUND", "NO_MANIFESTS", "TOO_LARGE", "TREE_TRUNCATED", "TOO_MANY_PACKAGES"]
  ops_errors  = ["GITHUB_RATE_LIMITED", "GITHUB_AUTH_FAILED", "SBOM_FAILED", "SBOM_INVALID", "TIMEOUT", "INTERNAL"]
  mark_failed = { for k, code in { User = "$.error.Error", Ops = "$.error.Error", Internal = "INTERNAL" } : k => {
    Type     = "Task"
    Resource = "arn:${local.p}:states:::dynamodb:updateItem"
    Parameters = {
      TableName = var.table_name
      Key = {
        pk = { "S.$" = "States.Format('SCAN#{}', $.scanId)" }
        sk = { S = "META" }
      }
      UpdateExpression         = "SET #s = :s, errorCode = :c, updatedAt = :u"
      ConditionExpression      = "attribute_exists(pk)"
      ExpressionAttributeNames = { "#s" = "status" }
      ExpressionAttributeValues = {
        ":s" = { S = "FAILED" }
        ":c" = k == "Internal" ? { S = "INTERNAL" } : { "S.$" = code }
        ":u" = { "S.$" = "$$.State.EnteredTime" }
      }
    }
    ResultPath = null
    Next       = k == "User" ? "ScanEnded" : "ScanFailed"
  } }

  definition = {
    Comment        = "Graveyard scan: validate, fetch, SBOM, graph, autopsy, classify, finalise"
    TimeoutSeconds = var.workflow_timeout_seconds
    StartAt        = "Validate"
    States = {
      Validate = {
        Type     = "Task"
        Resource = "arn:${local.p}:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.alias_arns["validate"]
          Payload      = { "scanId.$" = "$.scanId", "source.$" = "$.source" }
        }
        ResultSelector = { "limits.$" = "$.Payload.limits" }
        ResultPath     = "$.validate"
        Retry          = [local.lambda_retry]
        Catch          = local.catch_all
        Next           = "FetchManifests"
      }
      FetchManifests = {
        Type     = "Task"
        Resource = "arn:${local.p}:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.alias_arns["fetch"]
          Payload      = { "scanId.$" = "$.scanId", "source.$" = "$.source", "limits.$" = "$.validate.limits" }
        }
        ResultSelector = {
          "servicesKey.$"  = "$.Payload.servicesKey"
          "serviceItems.$" = "$.Payload.serviceItems"
          "services.$"     = "$.Payload.services"
          "files.$"        = "$.Payload.files"
          "bytes.$"        = "$.Payload.bytes"
        }
        ResultPath = "$.fetch"
        Retry      = [local.rate_limit_retry, local.lambda_retry]
        Catch      = local.catch_all
        Next       = "GenerateSBOM"
      }
      GenerateSBOM = {
        Type           = "Map"
        ItemsPath      = "$.fetch.serviceItems"
        MaxConcurrency = var.sbom_map_concurrency
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "Syft"
          States = {
            Syft = {
              Type     = "Task"
              Resource = "arn:${local.p}:states:::lambda:invoke"
              Parameters = {
                FunctionName = local.alias_arns["syft"]
                "Payload.$"  = "$"
              }
              ResultSelector = { "index.$" = "$.Payload.index", "sbomKey.$" = "$.Payload.sbomKey" }
              Retry          = [local.lambda_retry]
              End            = true
            }
          }
        }
        ResultPath = "$.sbom"
        Catch      = local.catch_all
        Next       = "BuildGraph"
      }
      BuildGraph = {
        Type     = "Task"
        Resource = "arn:${local.p}:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.alias_arns["graph"]
          Payload      = { "scanId.$" = "$.scanId", "limits.$" = "$.validate.limits" }
        }
        ResultSelector = {
          "purlsKey.$" = "$.Payload.purlsKey"
          "nodesKey.$" = "$.Payload.nodesKey"
          "total.$"    = "$.Payload.total"
          "asOf.$"     = "$.Payload.asOf"
        }
        ResultPath = "$.graph"
        Retry      = [local.lambda_retry]
        Catch      = local.catch_all
        Next       = "AutopsyMap"
      }
      AutopsyMap = {
        Type = "Map"
        ItemReader = {
          Resource     = "arn:${local.p}:states:::s3:getObject"
          ReaderConfig = { InputType = "JSON" }
          Parameters   = { Bucket = var.bucket_name, "Key.$" = "$.graph.purlsKey" }
        }
        ItemBatcher = {
          MaxItemsPerBatch = var.autopsy_batch_size
          BatchInput       = { "scanId.$" = "$.scanId", "asOf.$" = "$.graph.asOf" }
        }
        MaxConcurrency             = var.autopsy_map_concurrency
        ToleratedFailurePercentage = var.tolerated_failure_percentage
        ItemProcessor = {
          ProcessorConfig = { Mode = "DISTRIBUTED", ExecutionType = "EXPRESS" }
          StartAt         = "Autopsy"
          States = {
            Autopsy = {
              Type     = "Task"
              Resource = "arn:${local.p}:states:::lambda:invoke"
              Parameters = {
                FunctionName = local.alias_arns["autopsy"]
                Payload = {
                  "scanId.$" = "$.BatchInput.scanId"
                  "asOf.$"   = "$.BatchInput.asOf"
                  "Items.$"  = "$.Items"
                }
              }
              # Small on purpose: without a ResultWriter the batch results are collected in memory (256 KB).
              ResultSelector = {
                "ok.$"          = "$.Payload.ok"
                "cached.$"      = "$.Payload.cached"
                "failedCount.$" = "States.ArrayLength($.Payload.failed)"
              }
              Retry = [local.lambda_retry]
              End   = true
            }
          }
        }
        ResultPath = null
        Catch      = local.catch_all
        Next       = "Classify"
      }
      Classify = {
        Type     = "Task"
        Resource = "arn:${local.p}:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.alias_arns["classify"]
          Payload      = { "scanId.$" = "$.scanId", "asOf.$" = "$.graph.asOf", "nodesKey.$" = "$.graph.nodesKey" }
        }
        ResultSelector = { "counts.$" = "$.Payload.counts" }
        ResultPath     = "$.classify"
        Retry          = [local.lambda_retry]
        Catch          = local.catch_all
        Next           = "Finalise"
      }
      Finalise = {
        Type     = "Task"
        Resource = "arn:${local.p}:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.alias_arns["finalise"]
          Payload      = { "scanId.$" = "$.scanId", "counts.$" = "$.classify.counts" }
        }
        ResultPath = "$.finalise"
        Retry      = [local.lambda_retry]
        Catch      = local.catch_all
        End        = true
      }
      # Only fixed codes are written (SB-FIN-2): a name outside the two lists is stored as INTERNAL, never as text.
      HandleError = {
        Type = "Choice"
        Choices = [
          { Or = [for c in local.user_errors : { Variable = "$.error.Error", StringEquals = c }], Next = "MarkFailedUser" },
          { Or = [for c in local.ops_errors : { Variable = "$.error.Error", StringEquals = c }], Next = "MarkFailedOps" },
        ]
        Default = "MarkFailedInternal"
      }
      MarkFailedUser     = local.mark_failed["User"]
      MarkFailedOps      = local.mark_failed["Ops"]
      MarkFailedInternal = local.mark_failed["Internal"]
      # A scan that failed because of its input ends as a success of the workflow; an operational failure ends as a
      # failed execution, so the ExecutionsFailed alarm counts only those.
      ScanEnded  = { Type = "Succeed" }
      ScanFailed = { Type = "Fail", Error = "ScanFailed", Cause = "The scan failed; see the scan item." }
    }
  }

  sfn_statements = [
    { Sid = "InvokeTasks", Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = values(local.alias_arns) },
    { Sid = "StartOwnExecutions", Effect = "Allow", Action = ["states:StartExecution"], Resource = [local.machine_arn, local.alias_arn] },
    {
      Sid      = "OwnExecutions"
      Effect   = "Allow"
      Action   = ["states:DescribeExecution", "states:StopExecution"]
      Resource = ["arn:${local.p}:states:${local.region}:${local.account}:execution:${local.machine_name}:*", "arn:${local.p}:states:${local.region}:${local.account}:express:${local.machine_name}:*"]
    },
    local.st.s3_get,
    local.st.ddb_update,
    local.st.key,
    # Exceptions E1 and E2 (X-Ray) and E7 (log delivery, approved 19 Nov 2026): none of these supports a resource.
    { Sid = "ExceptionE1E2", Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = "*" },
    {
      Sid      = "ExceptionE7"
      Effect   = "Allow"
      Action   = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"]
      Resource = "*"
    },
  ]
}

resource "aws_lambda_layer_version" "syft" {
  layer_name               = "${var.name_prefix}-syft"
  description              = "Syft linux arm64 at /opt/bin/syft, pinned by SHA-256 (scripts/build/syft-pin.json)"
  filename                 = var.syft_layer_zip_path
  source_code_hash         = filebase64sha256(var.syft_layer_zip_path)
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
  lifecycle {
    precondition {
      condition     = filesha256(var.syft_layer_zip_path) == var.syft_layer_sha256
      error_message = "syft-layer.zip differs from the hash the plan was made with (SB-CI-2). Rebuild it with scripts/build/build_syft_layer.py."
    }
  }
}

module "fn" {
  source   = "../lambda-function"
  for_each = var.functions

  name                 = "${var.name_prefix}-${each.key}"
  env                  = var.env
  account_id           = var.account_id
  partition            = var.partition
  region               = var.region
  boundary_arn         = var.boundary_arn
  handler              = "workflow.${each.key}.handler"
  filename             = var.lambda_zip_path
  zip_sha256           = var.lambda_zip_sha256
  layers               = each.key == "syft" ? [aws_lambda_layer_version.syft.arn] : []
  memory_size          = each.value.memory_size
  timeout              = each.value.timeout
  reserved_concurrency = each.value.reserved_concurrency
  environment          = local.common_env
  statements           = local.tasks[each.key]
  log_retention_days   = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/${local.machine_name}"
  retention_in_days = var.log_retention_days
  # checkov:skip=CKV_AWS_158:Execution logs are at level ERROR without execution data (SB-WF-4); a CMK needs a key policy for the logs service.
  # checkov:skip=CKV_AWS_338:Retention is a variable; the default of 30 days is intended.
}

resource "aws_iam_role" "sfn" {
  name                 = "${local.machine_name}-sfn"
  path                 = local.role_path
  permissions_boundary = var.boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = var.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  name   = "${local.machine_name}-sfn"
  role   = aws_iam_role.sfn.name
  policy = jsonencode({ Version = "2012-10-17", Statement = local.sfn_statements })
}

resource "aws_sfn_state_machine" "scan" {
  name       = local.machine_name
  role_arn   = aws_iam_role.sfn.arn
  type       = "STANDARD"
  publish    = true
  definition = jsonencode(local.definition)
  logging_configuration {
    level                  = "ERROR"
    include_execution_data = false
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
  }
  tracing_configuration {
    enabled = true
  }
  # checkov:skip=CKV_AWS_285:Execution data is left out of the logs on purpose: inputs and outputs carry scan IDs, repo names and S3 keys (SB-WF-4). Errors are logged.
  depends_on = [module.fn, aws_iam_role_policy.sfn]
}

resource "aws_sfn_alias" "live" {
  name = "live"
  routing_configuration {
    state_machine_version_arn = aws_sfn_state_machine.scan.state_machine_version_arn
    weight                    = 100
  }
}
