# Plan role read policies (INF-PLAN-1): the read halves of the apply policies, for both envs, as explicit
# action lists. No write, no table item, no object, no secret value. The plan role can be used from a
# pull-request branch (accepted risk O8), so it reads configuration and metadata only.
locals {
  cond_read_all = {
    StringEquals = {
      "aws:ResourceTag/${local.tag_project_key}" = local.tag_project_value
      "aws:ResourceTag/Env"                      = local.env_list
    }
  }

  plan_read_policies = {
    "graveyard-plan-read-compute" = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "Lambda", Effect = "Allow", Action = local.act.lambda_read, Resource = [for e in local.env_list : local.res[e].function] },
        { Sid = "LambdaLayers", Effect = "Allow", Action = local.act.layer_read, Resource = [for e in local.env_list : local.res[e].layer] },
        { Sid = "StepFunctions", Effect = "Allow", Action = local.act.sfn_read, Resource = [for e in local.env_list : local.res[e].state_machine] },
        { Sid = "Ecr", Effect = "Allow", Action = local.act.ecr_read, Resource = [for e in local.env_list : local.res[e].repository] },
        { Sid = "Scheduler", Effect = "Allow", Action = local.act.scheduler_read, Resource = flatten([for e in local.env_list : [local.res[e].schedule, local.res[e].schedule_group]]) },
        { Sid = "XRay", Effect = "Allow", Action = local.act.xray_read, Resource = flatten([for e in local.env_list : [local.res[e].xray_group, local.res[e].xray_sampling]]) },
        { Sid = "ReadStar", Effect = "Allow", Action = local.star_reads.compute, Resource = "*" },
        # Exception E8 (20 Nov 2026): the provider validates the state machine definition while planning. No state change.
        { Sid = "ExceptionE8", Effect = "Allow", Action = local.exception_actions.e8_validate, Resource = "*" },
      ]
    })

    "graveyard-plan-read-data" = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "S3Buckets", Effect = "Allow", Action = local.act.s3_read, Resource = [for e in local.env_list : local.res[e].bucket] },
        { Sid = "DynamoDbTables", Effect = "Allow", Action = local.act.ddb_read, Resource = [for e in local.env_list : local.res[e].table] },
        { Sid = "KmsKeys", Effect = "Allow", Action = local.act.kms_read, Resource = [local.gen.kms_key], Condition = local.cond_read_all },
        { Sid = "Ssm", Effect = "Allow", Action = local.act.ssm_read, Resource = [for e in local.env_list : local.res[e].parameter] },
        { Sid = "SecretContainers", Effect = "Allow", Action = local.act.secret_read, Resource = [for e in local.env_list : local.res[e].secret] },
        { Sid = "ReadStar", Effect = "Allow", Action = local.star_reads.data, Resource = "*" },
      ]
    })

    "graveyard-plan-read-edge" = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "HttpApis", Effect = "Allow", Action = local.act.apigw_read, Resource = [local.gen.apis, local.gen.apis_all, local.gen.api_tags] },
        { Sid = "Distributions", Effect = "Allow", Action = local.act.cf_dist_read, Resource = [local.gen.distribution], Condition = local.cond_read_all },
        { Sid = "CloudFrontFunctions", Effect = "Allow", Action = local.act.cf_fn_read, Resource = [for e in local.env_list : local.res[e].cf_function] },
        { Sid = "Waf", Effect = "Allow", Action = local.act.waf_read, Resource = flatten([for e in local.env_list : local.res[e].waf]) },
        { Sid = "Acm", Effect = "Allow", Action = local.act.acm_read, Resource = local.gen.certificates, Condition = local.cond_read_all },
        { Sid = "ReadStar", Effect = "Allow", Action = local.star_reads.edge, Resource = "*" },
      ]
    })

    # infra-edge: the read halves of policies_apply_edge_extra.tf, for both envs. The record reads are on the one zone.
    "graveyard-plan-read-edge-extra" = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "Route53Read", Effect = "Allow", Action = local.act.edge_route53_read, Resource = [local.arn_zone] },
        { Sid = "EdgeAlarms", Effect = "Allow", Action = local.act.edge_alarm_read, Resource = [for e in local.env_list : local.res[e].alarm_us_east_1] },
        { Sid = "EdgeTopic", Effect = "Allow", Action = local.act.edge_topic_read, Resource = [for e in local.env_list : local.res[e].topic_us_east_1] },
      ]
    })
    "graveyard-plan-read-ops" = jsonencode({
      Version = "2012-10-17"
      Statement = [
        { Sid = "Logs", Effect = "Allow", Action = local.act.logs_read, Resource = flatten([for e in local.env_list : local.res[e].log_groups]) },
        { Sid = "CloudWatch", Effect = "Allow", Action = local.act.cw_read, Resource = flatten([for e in local.env_list : [local.res[e].alarm, local.res[e].dashboard]]) },
        { Sid = "Synthetics", Effect = "Allow", Action = local.act.syn_read, Resource = [for e in local.env_list : local.res[e].canary] },
        { Sid = "Sns", Effect = "Allow", Action = local.act.sns_read, Resource = [for e in local.env_list : local.res[e].topic] },
        { Sid = "Guardrails", Effect = "Allow", Action = local.act.br_read, Resource = [local.gen.guardrail], Condition = local.cond_read_all },
        { Sid = "ReadStar", Effect = "Allow", Action = local.star_reads.ops, Resource = "*" },
      ]
    })
  }
}
