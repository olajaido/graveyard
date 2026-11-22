# Apply role policies, part 2: the service policies (INF-APPLY-2, INF-APPLY-3, INF-SHARED-1..4, design 5.2.3).
# Every write is limited to a graveyard-<env> name or path, or to the Project and Env tags. Statements on
# "*" are reads, creates with the RequestTag condition, and the approved exceptions E4 and E6.
locals {
  apply_service_docs = { for e in local.env_list : e => {
    compute = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "Lambda", Effect = "Allow", Action = concat(local.act.lambda_write, local.act.lambda_read), Resource = [local.res[e].function] },
        { Sid = "LambdaLayers", Effect = "Allow", Action = concat(local.act.layer_write, local.act.layer_read), Resource = [local.res[e].layer] },
        { Sid = "StepFunctions", Effect = "Allow", Action = concat(local.act.sfn_write, local.act.sfn_read), Resource = [local.res[e].state_machine] },
        # Exception E8 (20 Nov 2026): validation of a state machine definition; the action has no resource.
        { Sid = "ExceptionE8", Effect = "Allow", Action = local.exception_actions.e8_validate, Resource = "*" },
        { Sid = "Ecr", Effect = "Allow", Action = concat(local.act.ecr_write, local.act.ecr_read), Resource = [local.res[e].repository] },
        { Sid = "Scheduler", Effect = "Allow", Action = concat(local.act.scheduler_write, local.act.scheduler_read), Resource = [local.res[e].schedule, local.res[e].schedule_group] },
        { Sid = "XRay", Effect = "Allow", Action = concat(local.act.xray_write, local.act.xray_read), Resource = [local.res[e].xray_group, local.res[e].xray_sampling] },
        # AWS requires * for xray:GetSamplingRules (it lists the account's sampling rules). Read only.
        { Sid = "ReadStar", Effect = "Allow", Action = local.star_reads.compute, Resource = "*" },
        # Exception E4 (approved 18 Nov 2026): AWS requires * for ecr:GetAuthorizationToken. It returns a registry token and changes nothing.
        { Sid = "ExceptionE4", Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      ]
    })

    data = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "S3Buckets", Effect = "Allow", Action = concat(local.act.s3_write, local.act.s3_read), Resource = [local.res[e].bucket] },
        { Sid = "DynamoDbTables", Effect = "Allow", Action = concat(local.act.ddb_write, local.act.ddb_read), Resource = [local.res[e].table] },
        # AWS requires * for kms:CreateKey (a new key has no ARN yet). Allowed only with the Project and Env tags in the request.
        { Sid = "KmsCreateKey", Effect = "Allow", Action = ["kms:CreateKey"], Resource = "*", Condition = local.cond_create[e] },
        { Sid = "KmsTagNewKey", Effect = "Allow", Action = ["kms:TagResource"], Resource = [local.gen.kms_key], Condition = local.cond_create[e] },
        { Sid = "KmsManageKeys", Effect = "Allow", Action = concat(local.act.kms_write, local.act.kms_read), Resource = [local.gen.kms_key], Condition = local.cond_use[e] },
        # scan-backend (19 Nov 2026): grants for AWS services (DynamoDB, Secrets Manager) on Graveyard keys only.
        { Sid = "KmsCreateGrant", Effect = "Allow", Action = local.act.kms_grant, Resource = [local.gen.kms_key], Condition = merge(local.cond_use[e], { Bool = { "kms:GrantIsForAWSResource" = "true" } }) },
        # Calls that DynamoDB, Secrets Manager and S3 make with the caller's credentials on a resource encrypted with the app
        # key. Only keys of this env and this project, and only through these three services in this region.
        {
          Sid      = "KmsUseViaServices"
          Effect   = "Allow"
          Action   = local.act.kms_via_service
          Resource = [local.gen.kms_key]
          Condition = {
            StringEquals = merge(local.cond_use[e].StringEquals, {
              "kms:ViaService" = [
                "dynamodb.${local.r}.amazonaws.com",
                "secretsmanager.${local.r}.amazonaws.com",
                "s3.${local.r}.amazonaws.com",
              ]
            })
          }
        },
        { Sid = "KmsAliases", Effect = "Allow", Action = local.act.alias_write, Resource = [local.res[e].kms_alias] },
        { Sid = "Ssm", Effect = "Allow", Action = concat(local.act.ssm_write, local.act.ssm_read), Resource = [local.res[e].parameter] },
        { Sid = "SecretContainers", Effect = "Allow", Action = concat(local.act.secret_write, local.act.secret_read), Resource = [local.res[e].secret] },
        # AWS requires * for kms:ListAliases and ssm:DescribeParameters. Metadata reads only.
        { Sid = "ReadStar", Effect = "Allow", Action = local.star_reads.data, Resource = "*" },
      ]
    })

    edge = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "CreateHttpApis", Effect = "Allow", Action = ["apigateway:POST"], Resource = [local.gen.apis], Condition = local.cond_create[e] },
        { Sid = "TagHttpApis", Effect = "Allow", Action = ["apigateway:PUT"], Resource = [local.gen.api_tags], Condition = local.cond_create[e] },
        { Sid = "ManageHttpApis", Effect = "Allow", Action = ["apigateway:GET", "apigateway:POST", "apigateway:PUT", "apigateway:PATCH", "apigateway:DELETE"], Resource = [local.gen.apis_all], Condition = local.cond_use[e] },
        # Exception E9 (20 Nov 2026): tags of HTTP APIs and their stages, written on create. No tag condition exists for POST here.
        # Tag-on-create of HTTP API children (the $default stage, 20 Nov 2026). AWS authorizes it as apigateway:TagResource (the
        # name in the error of the failed apply) and, per the Service Authorization Reference, CreateStage and TagResource as
        # apigateway:PUT and POST; both forms are allowed, only with this env's Project and Env tags in the request.
        { Sid = "TagHttpApiChildren", Effect = "Allow", Action = ["apigateway:TagResource", "apigateway:PUT", "apigateway:POST"], Resource = [local.gen.apis_all, local.gen.api_tags], Condition = local.cond_create[e] },
        { Sid = "UntagHttpApiChildren", Effect = "Allow", Action = ["apigateway:UntagResource"], Resource = [local.gen.apis_all, local.gen.api_tags], Condition = local.cond_use[e] },
        { Sid = "ExceptionE9", Effect = "Allow", Action = local.exception_actions.e9_api_tags, Resource = [local.gen.api_tags] },
        { Sid = "ReadHttpApis", Effect = "Allow", Action = local.act.apigw_read, Resource = [local.gen.apis, local.gen.api_tags] },
        # AWS requires * for cloudfront:CreateDistribution and CreateFunction (a new resource has no ARN yet). Only with the tags in the request.
        { Sid = "CreateDistributions", Effect = "Allow", Action = ["cloudfront:CreateDistribution"], Resource = "*", Condition = local.cond_create[e] },
        { Sid = "TagNewDistributions", Effect = "Allow", Action = ["cloudfront:TagResource"], Resource = [local.gen.distribution], Condition = local.cond_create[e] },
        { Sid = "ManageDistributions", Effect = "Allow", Action = concat(local.act.cf_dist_write, local.act.cf_dist_read), Resource = [local.gen.distribution], Condition = local.cond_use[e] },
        { Sid = "CreateCloudFrontFunctions", Effect = "Allow", Action = ["cloudfront:CreateFunction"], Resource = "*", Condition = local.cond_create[e] },
        { Sid = "ManageCloudFrontFunctions", Effect = "Allow", Action = concat(local.act.cf_fn_write, local.act.cf_fn_read), Resource = [local.res[e].cf_function] },
        # Exception E6 (approved 18 Nov 2026): origin access controls cannot be tagged or named, so the resource is *.
        # The maintainer's reason: AWS refuses to delete an origin access control that is attached to a distribution.
        { Sid = "ExceptionE6", Effect = "Allow", Action = ["cloudfront:CreateOriginAccessControl", "cloudfront:GetOriginAccessControl", "cloudfront:ListOriginAccessControls", "cloudfront:UpdateOriginAccessControl", "cloudfront:DeleteOriginAccessControl"], Resource = "*" },
        { Sid = "Waf", Effect = "Allow", Action = concat(local.act.waf_write, local.act.waf_read), Resource = local.res[e].waf },
        # AWS requires * for acm:RequestCertificate (a new certificate has no ARN yet). Only with the tags in the request.
        { Sid = "AcmRequest", Effect = "Allow", Action = ["acm:RequestCertificate"], Resource = "*", Condition = local.cond_create[e] },
        { Sid = "AcmTagNew", Effect = "Allow", Action = ["acm:AddTagsToCertificate"], Resource = local.gen.certificates, Condition = local.cond_create[e] },
        { Sid = "AcmManage", Effect = "Allow", Action = concat(local.act.acm_write, local.act.acm_read), Resource = local.gen.certificates, Condition = local.cond_use[e] },
        # AWS requires * for these list and metadata reads (distributions, managed CloudFront policies, WAF, certificates).
        { Sid = "ReadStar", Effect = "Allow", Action = local.star_reads.edge, Resource = "*" },
      ]
    })

    ops = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "Logs", Effect = "Allow", Action = concat(local.act.logs_write, local.act.logs_read), Resource = local.res[e].log_groups },
        { Sid = "CloudWatch", Effect = "Allow", Action = concat(local.act.cw_write, local.act.cw_read), Resource = [local.res[e].alarm, local.res[e].dashboard] },
        { Sid = "Synthetics", Effect = "Allow", Action = concat(local.act.syn_write, local.act.syn_read), Resource = [local.res[e].canary] },
        { Sid = "Sns", Effect = "Allow", Action = concat(local.act.sns_write, local.act.sns_read), Resource = [local.res[e].topic] },
        # AWS requires * for bedrock:CreateGuardrail (a new guardrail has no ARN yet). Only with the tags in the request.
        { Sid = "CreateGuardrails", Effect = "Allow", Action = ["bedrock:CreateGuardrail"], Resource = "*", Condition = local.cond_create[e] },
        { Sid = "TagNewGuardrails", Effect = "Allow", Action = ["bedrock:TagResource"], Resource = [local.gen.guardrail], Condition = local.cond_create[e] },
        { Sid = "ManageGuardrails", Effect = "Allow", Action = concat(local.act.br_write, local.act.br_read), Resource = [local.gen.guardrail], Condition = local.cond_use[e] },
        # Exception E7 (approved 19 Nov 2026): log delivery for Step Functions and API Gateway logs. No resource-level permissions.
        { Sid = "ExceptionE7", Effect = "Allow", Action = local.act.logs_delivery, Resource = "*" },
        # AWS requires * for these list and describe calls. Metadata reads only.
        { Sid = "ReadStar", Effect = "Allow", Action = local.star_reads.ops, Resource = "*" },
      ]
    })
  } }
}
