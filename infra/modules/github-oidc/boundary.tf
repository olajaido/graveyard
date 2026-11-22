# Workload boundaries (INF-APPLY-7, INF-SHARED-1..4, design 5.2.6). One per env, on the CI path, attached to
# every workload role of that env by the spec that creates the role. A boundary only caps: each role still
# gets its own narrower policy (PRD 13.2). Write actions are limited to the env's names and paths or the
# Project and Env tags; the four exceptions that AWS cannot scope (E1, E2, E3, E5) are listed as Exception*.
locals {
  bedrock_profiles = {
    narrate = var.bedrock_narrate_profile_id
    rites   = var.bedrock_rites_profile_id
  }

  # Exact ARNs (INF-SHARED-6): the inference profile in eu-west-2 and the foundation model, in each configured
  # region, that the profile routes to. The model ID is the profile ID without the eu. prefix.
  bedrock_profile_arn = { for k, id in local.bedrock_profiles : k => "arn:${local.p}:bedrock:${local.r}:${local.a}:inference-profile/${id}" }
  bedrock_model_arns = { for k, id in local.bedrock_profiles : k => [
    for region in var.bedrock_foundation_model_regions : "arn:${local.p}:bedrock:${region}::foundation-model/${trimprefix(id, "eu.")}"
  ] }

  # Region deny for workload roles (INF-REG-2, V20). Cross-region inference is evaluated in each destination
  # region, so the general deny would block calls routed outside eu-west-2. bedrock:InvokeModel is therefore
  # handled only by DenyInvokeModelOutsideRegion: it is denied outside the region unless the call came through
  # one of the two approved profiles. A negated operator is true when the key is absent (IAM docs), so a direct
  # call with no bedrock:InferenceProfileArn is still denied. Every other action, including
  # bedrock:InvokeModelWithResponseStream, stays under the general deny.
  boundary_region_deny = concat(
    [
      merge(local.region_deny[0], { NotAction = concat(local.region_deny[0].NotAction, ["bedrock:InvokeModel"]) }),
      {
        Sid      = "DenyInvokeModelOutsideRegion"
        Effect   = "Deny"
        Action   = ["bedrock:InvokeModel"]
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "aws:RequestedRegion"         = local.r
            "bedrock:InferenceProfileArn" = [local.bedrock_profile_arn.narrate, local.bedrock_profile_arn.rites]
          }
        }
      },
    ],
    slice(local.region_deny, 1, length(local.region_deny)),
  )
  boundary_docs = { for e in local.env_list : e => jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        { Sid = "LogsWrite", Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = slice(local.res[e].log_groups, 0, 3) },
        { Sid = "SsmRead", Effect = "Allow", Action = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"], Resource = [local.res[e].parameter, trimsuffix(local.res[e].parameter, "/*")] },
        { Sid = "KmsUse", Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = [local.gen.kms_key], Condition = local.cond_use[e] },
        { Sid = "DynamoDbItems", Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchWriteItem"], Resource = [local.res[e].table] },
        { Sid = "S3Objects", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"], Resource = [local.res[e].bucket] },
        { Sid = "StatesExecute", Effect = "Allow", Action = ["states:StartExecution", "states:DescribeExecution", "states:StopExecution"], Resource = [local.res[e].state_machine, "arn:${local.p}:states:${local.r}:${local.a}:execution:graveyard-${e}-*"] },
        # scan-backend (19 Nov 2026): the Distributed Map runs Express child executions, whose ARNs use the express: type.
        { Sid = "StatesExpressExecutions", Effect = "Allow", Action = ["states:DescribeExecution", "states:StopExecution"], Resource = ["arn:${local.p}:states:${local.r}:${local.a}:express:graveyard-${e}-*"] },
        { Sid = "LambdaInvoke", Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [local.res[e].function] },
        { Sid = "SecretValues", Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [local.res[e].secret] },
        { Sid = "SnsPublish", Effect = "Allow", Action = ["sns:Publish"], Resource = [local.res[e].topic] },
        { Sid = "ApplyGuardrail", Effect = "Allow", Action = ["bedrock:ApplyGuardrail"], Resource = [local.gen.guardrail], Condition = local.cond_use[e] },

        # Exceptions E1 and E2 (approved 18 Nov 2026): X-Ray has no resource-level permissions. Boundary only.
        { Sid = "ExceptionE1", Effect = "Allow", Action = ["xray:PutTraceSegments"], Resource = "*" },
        { Sid = "ExceptionE2", Effect = "Allow", Action = ["xray:PutTelemetryRecords"], Resource = "*" },
        # Exception E3: PutMetricData has no resource ARN; the namespace condition is the limit.
        { Sid = "ExceptionE3", Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*", Condition = { StringEquals = { "cloudwatch:namespace" = "Graveyard/${e}" } } },
        # Exception E7 (log delivery) is no longer in the boundary: E10 below holds the same actions plus logs:PutResourcePolicy,
        # and only for state machine roles (20 Nov 2026). E7 stays in the apply roles.
        # Exception E10 (approved 20 Nov 2026): log-delivery management for Step Functions execution logging. No resource-level
        # permissions, so the resource is *; the principal condition limits it to this env's state machine roles.
        {
          Sid       = "ExceptionE10"
          Effect    = "Allow"
          Action    = local.exception_actions.e10_sfn_logging
          Resource  = "*"
          Condition = { ArnLike = { "aws:PrincipalArn" = local.sfn_role_pattern[e] } }
        },
        # Exception E5 (approved, narrowed 18 Nov 2026): the exact profiles and the exact foundation models behind them.
        # No eu-* and no foundation-model/*. The model statements also require the call to come through its own profile.
        { Sid = "ExceptionE5Profiles", Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], Resource = [local.bedrock_profile_arn.narrate, local.bedrock_profile_arn.rites] },
        {
          Sid       = "ExceptionE5ModelNarrate"
          Effect    = "Allow"
          Action    = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
          Resource  = local.bedrock_model_arns.narrate
          Condition = { StringEquals = { "bedrock:InferenceProfileArn" = local.bedrock_profile_arn.narrate } }
        },
        {
          Sid       = "ExceptionE5ModelRites"
          Effect    = "Allow"
          Action    = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
          Resource  = local.bedrock_model_arns.rites
          Condition = { StringEquals = { "bedrock:InferenceProfileArn" = local.bedrock_profile_arn.rites } }
        },

        { Sid = "DenyIam", Effect = "Deny", Action = ["iam:*"], Resource = "*" },
        { Sid = "DenyCost", Effect = "Deny", Action = ["budgets:*", "ce:*"], Resource = "*" },
      ],
      local.boundary_region_deny,
    )
  }) }

  boundary_policies = { for e in local.env_list : "graveyard-${e}-boundary" => local.boundary_docs[e] }
}
