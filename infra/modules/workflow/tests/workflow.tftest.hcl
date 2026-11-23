# Offline tests for the workflow module (SB-WF-1 to SB-WF-6, SB-INF-3 to SB-INF-5, SB-TEST-4). The state machine
# definition is decoded from the plan and checked as data.
mock_provider "aws" {}
variables {
  name_prefix               = "graveyard-dev"
  env                       = "dev"
  account_id                = "123456789012"
  boundary_arn              = "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary"
  table_name                = "graveyard-dev-data"
  table_arn                 = "arn:aws:dynamodb:eu-west-2:123456789012:table/graveyard-dev-data"
  bucket_name               = "graveyard-dev-artefacts-20260101"
  bucket_arn                = "arn:aws:s3:::graveyard-dev-artefacts-20260101"
  kms_key_arn               = "arn:aws:kms:eu-west-2:123456789012:key/00000000-0000-0000-0000-000000000000"
  reader_secret_arn         = "arn:aws:secretsmanager:eu-west-2:123456789012:secret:graveyard/dev/github/reader-AbCdEf"
  reader_secret_name        = "graveyard/dev/github/reader"
  ssm_parameter_arn_pattern = "arn:aws:ssm:eu-west-2:123456789012:parameter/graveyard/dev/*"
  lambda_zip_path           = "tests/fixtures/lambda.zip"
  lambda_zip_sha256         = "9940df3df16c98c88fcc166e2fe9bd3fb6c2dc3c4e7b36254445ea3cae987a5d"
  syft_layer_zip_path       = "tests/fixtures/syft-layer.zip"
  syft_layer_sha256         = "9940df3df16c98c88fcc166e2fe9bd3fb6c2dc3c4e7b36254445ea3cae987a5d"
}
run "seven_functions_with_the_live_alias_and_the_layer_on_syft_only" {
  command = plan
  assert {
    condition     = toset(keys(module.fn)) == toset(["validate", "fetch", "syft", "graph", "autopsy", "classify", "finalise"])
    error_message = "Seven task functions."
  }
  assert {
    condition     = alltrue([for k, m in module.fn : m.function_name == "graveyard-dev-${k}"])
    error_message = "Names start with graveyard-<env>-."
  }
  assert {
    condition     = aws_lambda_layer_version.syft.layer_name == "graveyard-dev-syft" && one(aws_lambda_layer_version.syft.compatible_architectures) == "arm64"
    error_message = "The Syft layer for arm64."
  }
}
run "the_state_machine_is_standard_traced_logged_and_published" {
  command = plan
  assert {
    condition     = aws_sfn_state_machine.scan.name == "graveyard-dev-scan" && aws_sfn_state_machine.scan.type == "STANDARD" && aws_sfn_state_machine.scan.publish
    error_message = "A published Standard state machine graveyard-<env>-scan."
  }
  assert {
    condition     = one(aws_sfn_state_machine.scan.tracing_configuration).enabled
    error_message = "X-Ray on."
  }
  assert {
    condition     = one(aws_sfn_state_machine.scan.logging_configuration).level == "ERROR" && one(aws_sfn_state_machine.scan.logging_configuration).include_execution_data == false
    error_message = "Logging at ERROR without execution data (SB-WF-4)."
  }
  assert {
    condition     = aws_cloudwatch_log_group.sfn.name == "/aws/vendedlogs/states/graveyard-dev-scan"
    error_message = "The vended log group of the state machine."
  }
  assert {
    condition     = aws_sfn_alias.live.name == "live" && output.state_machine_alias_arn == "arn:aws:states:eu-west-2:123456789012:stateMachine:graveyard-dev-scan:live"
    error_message = "The live alias."
  }
}
run "the_workflow_has_the_states_in_order_and_a_five_minute_timeout" {
  command = plan
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).TimeoutSeconds == 300
    error_message = "300 seconds (PRD section 10.6)."
  }
  assert {
    condition     = [for s in ["Validate", "FetchManifests", "StageSbom", "GenerateSBOM", "BuildGraph", "StageAutopsy", "AutopsyMap", "Classify", "Finalise"] : jsondecode(aws_sfn_state_machine.scan.definition).States[s].Type] == ["Task", "Task", "Task", "Map", "Task", "Task", "Map", "Task", "Task"]
    error_message = "Nine states in the main line: the seven of SB-WF-1 and the two stage writes of ui-core B1 and B2; two of them maps."
  }
  assert {
    condition = [
      for s in ["Validate", "FetchManifests", "StageSbom", "GenerateSBOM", "BuildGraph", "StageAutopsy", "AutopsyMap", "Classify"] : jsondecode(aws_sfn_state_machine.scan.definition).States[s].Next
    ] == ["FetchManifests", "StageSbom", "GenerateSBOM", "BuildGraph", "StageAutopsy", "AutopsyMap", "Classify", "Finalise"]
    error_message = "The order is Validate to Finalise."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.Finalise.End == true
    error_message = "Finalise ends the workflow."
  }
}
run "every_state_that_can_fail_catches_to_handle_error" {
  command = plan
  assert {
    condition = alltrue([
      for s in ["Validate", "FetchManifests", "StageSbom", "GenerateSBOM", "BuildGraph", "StageAutopsy", "AutopsyMap", "Classify", "Finalise"] :
      jsondecode(aws_sfn_state_machine.scan.definition).States[s].Catch[0].ErrorEquals == ["States.ALL"] && jsondecode(aws_sfn_state_machine.scan.definition).States[s].Catch[0].Next == "HandleError"
    ])
    error_message = "A Catch for States.ALL to HandleError on every state (SB-WF-2)."
  }
  assert {
    condition = alltrue([
      for s in ["MarkFailedUser", "MarkFailedOps", "MarkFailedInternal"] :
      jsondecode(aws_sfn_state_machine.scan.definition).States[s].Resource == "arn:aws:states:::dynamodb:updateItem"
    ])
    error_message = "A failure is recorded through the DynamoDB service integration, not a Lambda (SB-FIN-2)."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.MarkFailedInternal.Parameters.ExpressionAttributeValues[":c"] == { S = "INTERNAL" }
    error_message = "An unknown error is stored as the fixed code INTERNAL."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.MarkFailedUser.Next == "ScanEnded" && jsondecode(aws_sfn_state_machine.scan.definition).States.MarkFailedOps.Next == "ScanFailed"
    error_message = "Input errors end as a success of the workflow; operational errors as a failed execution."
  }
  assert {
    condition     = length(jsondecode(aws_sfn_state_machine.scan.definition).States.HandleError.Choices[0].Or) == 6 && length(jsondecode(aws_sfn_state_machine.scan.definition).States.HandleError.Choices[1].Or) == 6
    error_message = "All twelve codes of SB-ERR-1 are routed (INTERNAL is the default and also listed)."
  }
}
run "the_autopsy_map_is_distributed_express_with_the_batcher_from_the_variable" {
  command = plan
  variables {
    autopsy_batch_size      = 40
    autopsy_map_concurrency = 15
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemBatcher.MaxItemsPerBatch == 40
    error_message = "MaxItemsPerBatch follows the variable."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.MaxConcurrency == 15
    error_message = "MaxConcurrency follows the variable."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.ProcessorConfig == { Mode = "DISTRIBUTED", ExecutionType = "EXPRESS" }
    error_message = "Distributed Map with Express children."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemReader.Parameters.Bucket == "graveyard-dev-artefacts-20260101" && jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemReader.Resource == "arn:aws:states:::s3:getObject"
    error_message = "The purl list is read from the artefacts bucket."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ResultPath == null && jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ToleratedFailurePercentage == 20
    error_message = "The map output is discarded (SB-WF-3) and 20 percent of batches may fail (SB-AUT-4)."
  }
}
run "the_defaults_are_50_and_20" {
  command = plan
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemBatcher.MaxItemsPerBatch == 50 && jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.MaxConcurrency == 20
    error_message = "PRD section 10.6 and the review: batch 50, concurrency 20."
  }
}
run "only_live_alias_arns_are_invoked" {
  command = plan
  assert {
    condition = alltrue(flatten([
      for s in ["Validate", "FetchManifests", "BuildGraph", "Classify", "Finalise"] :
      [endswith(jsondecode(aws_sfn_state_machine.scan.definition).States[s].Parameters.FunctionName, ":live")]
    ]))
    error_message = "Tasks invoke the live alias, never $LATEST (terraform.md)."
  }
  assert {
    condition     = endswith(jsondecode(aws_sfn_state_machine.scan.definition).States.GenerateSBOM.ItemProcessor.States.Syft.Parameters.FunctionName, "graveyard-dev-syft:live") && endswith(jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.Autopsy.Parameters.FunctionName, "graveyard-dev-autopsy:live")
    error_message = "The two maps invoke the live alias too."
  }
  assert {
    condition     = alltrue([for a in jsondecode(aws_iam_role_policy.sfn.policy).Statement[0].Resource : endswith(a, ":live")])
    error_message = "The state machine role may invoke only live aliases."
  }
}
run "retries_cover_lambda_service_errors_and_one_github_rate_limit_wait" {
  command = plan
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.Validate.Retry[0].MaxAttempts == 3 && jsondecode(aws_sfn_state_machine.scan.definition).States.Validate.Retry[0].JitterStrategy == "FULL" && jsondecode(aws_sfn_state_machine.scan.definition).States.Validate.Retry[0].BackoffRate == 2
    error_message = "Three attempts, backoff 2, full jitter (SB-WF-5)."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.FetchManifests.Retry[0].ErrorEquals == ["GITHUB_RATE_LIMITED"] && jsondecode(aws_sfn_state_machine.scan.definition).States.FetchManifests.Retry[0].MaxAttempts == 1
    error_message = "One retry for the GitHub rate limit."
  }
}
run "each_role_has_the_statements_of_sb_inf_5_and_nothing_else" {
  command = plan
  assert {
    condition = jsonencode({ for k, m in module.fn : k => sort(distinct(flatten([
      for s in jsondecode(m.role_policy_json).Statement : s.Action
      ]))) }) == jsonencode({
      validate = ["dynamodb:UpdateItem", "kms:Decrypt", "kms:GenerateDataKey", "logs:CreateLogStream", "logs:PutLogEvents", "ssm:GetParameter", "ssm:GetParameters", "xray:PutTelemetryRecords", "xray:PutTraceSegments"]
      fetch    = ["dynamodb:UpdateItem", "kms:Decrypt", "kms:GenerateDataKey", "logs:CreateLogStream", "logs:PutLogEvents", "s3:PutObject", "secretsmanager:GetSecretValue", "ssm:GetParameter", "ssm:GetParameters", "xray:PutTelemetryRecords", "xray:PutTraceSegments"]
      syft     = ["kms:Decrypt", "kms:GenerateDataKey", "logs:CreateLogStream", "logs:PutLogEvents", "s3:GetObject", "s3:PutObject", "xray:PutTelemetryRecords", "xray:PutTraceSegments"]
      graph    = ["dynamodb:UpdateItem", "kms:Decrypt", "kms:GenerateDataKey", "logs:CreateLogStream", "logs:PutLogEvents", "s3:GetObject", "s3:PutObject", "xray:PutTelemetryRecords", "xray:PutTraceSegments"]
      autopsy  = ["dynamodb:BatchGetItem", "dynamodb:GetItem", "dynamodb:PutItem", "kms:Decrypt", "kms:GenerateDataKey", "logs:CreateLogStream", "logs:PutLogEvents", "secretsmanager:GetSecretValue", "ssm:GetParameter", "ssm:GetParameters", "xray:PutTelemetryRecords", "xray:PutTraceSegments"]
      classify = ["dynamodb:BatchGetItem", "dynamodb:BatchWriteItem", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "kms:Decrypt", "kms:GenerateDataKey", "logs:CreateLogStream", "logs:PutLogEvents", "s3:GetObject", "xray:PutTelemetryRecords", "xray:PutTraceSegments"]
      finalise = ["dynamodb:GetItem", "dynamodb:UpdateItem", "kms:Decrypt", "kms:GenerateDataKey", "logs:CreateLogStream", "logs:PutLogEvents", "xray:PutTelemetryRecords", "xray:PutTraceSegments"]
    })
    error_message = "Each function gets exactly the actions of SB-INF-5 (and finalise reads its scan item)."
  }
  assert {
    condition     = alltrue([for k in ["syft", "autopsy"] : !contains(flatten([for s in jsondecode(module.fn[k].role_policy_json).Statement : s.Action]), "s3:DeleteObject")])
    error_message = "Nothing deletes objects; the lifecycle does."
  }
}
run "autopsy_has_no_s3_and_syft_has_no_secrets_dynamodb_or_ssm" {
  command = plan
  assert {
    condition     = !anytrue([for a in flatten([for s in jsondecode(module.fn["autopsy"].role_policy_json).Statement : s.Action]) : startswith(a, "s3:") || startswith(a, "bedrock:")])
    error_message = "autopsy: no S3, no Bedrock (security.md)."
  }
  assert {
    condition     = !anytrue([for a in flatten([for s in jsondecode(module.fn["syft"].role_policy_json).Statement : s.Action]) : startswith(a, "dynamodb:") || startswith(a, "secretsmanager:") || startswith(a, "ssm:")])
    error_message = "syft: no DynamoDB, Secrets Manager or SSM (SB-SBOM-5)."
  }
}
run "the_state_machine_role_uses_star_only_for_x_ray_and_log_delivery" {
  command = plan
  assert {
    condition     = [for s in jsondecode(aws_iam_role_policy.sfn.policy).Statement : s.Sid if s.Resource == "*"] == ["ExceptionE1E2", "ExceptionE10"]
    error_message = "Only the approved exceptions use *."
  }
  assert {
    condition     = aws_iam_role.sfn.path == "/graveyard-dev/" && aws_iam_role.sfn.permissions_boundary == "arn:aws:iam::123456789012:policy/graveyard-ci/graveyard-dev-boundary"
    error_message = "The role is on the workload path with the boundary."
  }
  assert {
    condition     = contains(flatten([for s in jsondecode(aws_iam_role_policy.sfn.policy).Statement : s.Resource if s.Sid == "OwnExecutions"]), "arn:aws:states:eu-west-2:123456789012:express:graveyard-dev-scan:*")
    error_message = "Express executions of the Distributed Map are covered."
  }
}
run "the_function_environment_holds_names_only" {
  command = plan
  assert {
    condition     = alltrue([for k, m in module.fn : !anytrue([for v in values(m.environment) : can(regex("BEGIN|ghs_|ghp_|AKIA", v))])])
    error_message = "No key, token or access key in an environment variable (SB-CFG-3)."
  }
  assert {
    condition     = module.fn["fetch"].environment["READER_SECRET_ID"] == "graveyard/dev/github/reader"
    error_message = "The secret is referred to by name."
  }
}
run "concurrency_totals_stay_near_fifty_with_the_api" {
  command = plan
  assert {
    condition     = sum([for f in var.functions : f.reserved_concurrency]) + 8 <= 52
    error_message = "About 50 reserved executions per env, api included (the review of 19 Nov 2026)."
  }
  assert {
    condition     = var.functions["autopsy"].reserved_concurrency == var.autopsy_map_concurrency
    error_message = "autopsy matches the Distributed Map MaxConcurrency."
  }
}
run "a_changed_zip_stops_the_apply" {
  command = plan
  variables {
    syft_layer_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
  }
  expect_failures = [aws_lambda_layer_version.syft]
}
run "the_state_machine_role_has_exception_e10_for_execution_logging" {
  command = plan
  assert {
    condition = [for s in jsondecode(aws_iam_role_policy.sfn.policy).Statement : s if s.Sid == "ExceptionE10"][0] == {
      Sid      = "ExceptionE10"
      Effect   = "Allow"
      Action   = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"]
      Resource = "*"
    }
    error_message = "E10: the eight log-delivery actions Step Functions requires, on * (no resource-level permissions)."
  }
  assert {
    condition     = [for s in jsondecode(aws_iam_role_policy.sfn.policy).Statement : s.Resource if s.Sid == "OwnLogGroup"][0] == ["arn:aws:logs:eu-west-2:123456789012:log-group:/aws/vendedlogs/states/graveyard-dev-scan:*"]
    error_message = "Log streams and events only in the state machine's own log group."
  }
  assert {
    condition     = endswith(aws_iam_role.sfn.name, "-sfn") && startswith(aws_iam_role.sfn.name, "graveyard-dev-")
    error_message = "The role name must match graveyard-<env>-*-sfn, the pattern the boundary allows E10 to."
  }
  assert {
    condition     = !anytrue([for k, m in module.fn : contains(flatten([for s in jsondecode(m.role_policy_json).Statement : s.Action]), "logs:PutResourcePolicy")])
    error_message = "No task function gets logs:PutResourcePolicy; E10 is for the state machine role only."
  }
}
# ui-core B1 and B2: stage values SBOM and AUTOPSY, and the best-effort progress counter.
run "the_sbom_and_autopsy_stages_are_written_by_the_state_machine_with_dynamodb_integrations" {
  command = plan
  assert {
    condition = alltrue([
      for s in ["StageSbom", "StageAutopsy"] :
      jsondecode(aws_sfn_state_machine.scan.definition).States[s].Resource == "arn:aws:states:::dynamodb:updateItem" && jsondecode(aws_sfn_state_machine.scan.definition).States[s].Parameters.TableName == "graveyard-dev-data" && jsondecode(aws_sfn_state_machine.scan.definition).States[s].Parameters.Key.sk == { S = "META" } && jsondecode(aws_sfn_state_machine.scan.definition).States[s].Parameters.ConditionExpression == "attribute_exists(pk)" && jsondecode(aws_sfn_state_machine.scan.definition).States[s].ResultPath == null
    ])
    error_message = "Both stage writes are UpdateItem on the scan META item, not a Lambda (ui-core B1)."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.StageSbom.Parameters.ExpressionAttributeValues[":s"] == { S = "SBOM" } && jsondecode(aws_sfn_state_machine.scan.definition).States.StageAutopsy.Parameters.ExpressionAttributeValues[":s"] == { S = "AUTOPSY" }
    error_message = "The stage values are SBOM and AUTOPSY."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.StageAutopsy.Parameters.UpdateExpression == "SET stage = :s, progressTotal = :t, progressExamined = :z, updatedAt = :u" && jsondecode(aws_sfn_state_machine.scan.definition).States.StageAutopsy.Parameters.ExpressionAttributeValues[":z"] == { N = "0" } && jsondecode(aws_sfn_state_machine.scan.definition).States.StageAutopsy.Parameters.ExpressionAttributeValues[":t"] == { "N.$" = "States.Format('{}', $.graph.total)" }
    error_message = "StageAutopsy sets the total from the graph and zeroes the counter (ui-core B2)."
  }
}
run "count_batch_adds_the_batch_size_and_can_never_fail_a_batch" {
  command = plan
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.Autopsy.Next == "CountBatch" && jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.Autopsy.ResultPath == "$.autopsy"
    error_message = "The autopsy result is kept under $.autopsy so that CountBatch can read BatchInput.scanId."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.CountBatch.Resource == "arn:aws:states:::dynamodb:updateItem" && jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.CountBatch.Parameters.UpdateExpression == "ADD progressExamined :n"
    error_message = "The counter is an atomic ADD."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.CountBatch.Parameters.ExpressionAttributeValues[":n"] == { "N.$" = "States.Format('{}', States.MathAdd(States.MathAdd($.autopsy.ok, $.autopsy.cached), $.autopsy.failedCount))" }
    error_message = "The batch size is ok + cached + failed."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.CountBatch.Catch == [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "Counted" }] && jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.CountBatch.Next == "Counted"
    error_message = "Progress is best effort: every error of CountBatch continues to Counted (never to HandleError, never fails the batch)."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.States.Counted == { Type = "Pass", Result = { counted = true }, ResultPath = "$", End = true }
    error_message = "The child ends with a tiny output, so the Items list is never collected (SB-WF-3)."
  }
  assert {
    condition     = jsondecode(aws_sfn_state_machine.scan.definition).States.AutopsyMap.ItemProcessor.ProcessorConfig == { Mode = "DISTRIBUTED", ExecutionType = "EXPRESS" }
    error_message = "Still a Distributed Map with Express children."
  }
}
