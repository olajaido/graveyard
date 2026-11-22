# Action lists and resource ARNs shared by the apply policies (write + read) and the plan read
# policies (read only). Explicit actions only: no wildcard in an Allow action (INF-SHARED-1).
# Reads are `Get*`, `List*` and `Describe*` actions; every other action is a write (design 5.2.7).
locals {
  # Resource ARNs by env. Names and paths contain graveyard-<env>- or graveyard/<env>/ (INF-SHARED-1(a));
  # resources whose identifier AWS generates use ARN patterns and are scoped by the Project tag instead.
  res = { for e in local.env_list : e => {
    bucket         = "arn:${local.p}:s3:::graveyard-${e}-*"
    table          = "arn:${local.p}:dynamodb:${local.r}:${local.a}:table/graveyard-${e}-*"
    function       = "arn:${local.p}:lambda:${local.r}:${local.a}:function:graveyard-${e}-*"
    layer          = "arn:${local.p}:lambda:${local.r}:${local.a}:layer:graveyard-${e}-*"
    state_machine  = "arn:${local.p}:states:${local.r}:${local.a}:stateMachine:graveyard-${e}-*"
    repository     = "arn:${local.p}:ecr:${local.r}:${local.a}:repository/graveyard-${e}-*"
    schedule       = "arn:${local.p}:scheduler:${local.r}:${local.a}:schedule/graveyard-${e}-*"
    schedule_group = "arn:${local.p}:scheduler:${local.r}:${local.a}:schedule-group/graveyard-${e}-*"
    xray_group     = "arn:${local.p}:xray:${local.r}:${local.a}:group/graveyard-${e}-*"
    xray_sampling  = "arn:${local.p}:xray:${local.r}:${local.a}:sampling-rule/graveyard-${e}-*"
    parameter      = "arn:${local.p}:ssm:${local.r}:${local.a}:parameter/graveyard/${e}/*"
    secret         = "arn:${local.p}:secretsmanager:${local.r}:${local.a}:secret:graveyard/${e}/*"
    kms_alias      = "arn:${local.p}:kms:${local.r}:${local.a}:alias/graveyard-${e}-*"
    topic          = "arn:${local.p}:sns:${local.r}:${local.a}:graveyard-${e}-*"
    alarm          = "arn:${local.p}:cloudwatch:${local.r}:${local.a}:alarm:graveyard-${e}-*"
    dashboard      = "arn:${local.p}:cloudwatch::${local.a}:dashboard/graveyard-${e}-*"
    canary         = "arn:${local.p}:synthetics:${local.r}:${local.a}:canary:graveyard-${e}-*"
    cf_function    = "arn:${local.p}:cloudfront::${local.a}:function/graveyard-${e}-*"
    log_groups = [
      "arn:${local.p}:logs:${local.r}:${local.a}:log-group:/aws/lambda/graveyard-${e}-*",
      "arn:${local.p}:logs:${local.r}:${local.a}:log-group:/aws/vendedlogs/states/graveyard-${e}-*",
      "arn:${local.p}:logs:${local.r}:${local.a}:log-group:/graveyard/${e}/*",
      "arn:${local.p}:logs:${local.r}:${local.a}:log-group:aws-waf-logs-graveyard-${e}-*",
    ]
    waf = flatten([for scope in [{ name = "regional", region = local.r }, { name = "global", region = local.global_region }] : [
      for kind in ["webacl", "ipset", "rulegroup"] : "arn:${local.p}:wafv2:${scope.region}:${local.a}:${scope.name}/${kind}/graveyard-${e}-*/*"
    ]])
  } }

  # Workload roles that may use exception E10: the state machine roles of each env (path /graveyard-<env>/, name ...-sfn).
  sfn_role_pattern = { for e in local.env_list : e => "arn:${local.p}:iam::${local.a}:role/graveyard-${e}/graveyard-${e}-*-sfn" }
  # Resources whose identifier AWS generates. They are written only with the Project tag condition.
  gen = {
    kms_key      = "arn:${local.p}:kms:${local.r}:${local.a}:key/*"
    guardrail    = "arn:${local.p}:bedrock:${local.r}:${local.a}:guardrail/*"
    apis         = "arn:${local.p}:apigateway:${local.r}::/apis"
    apis_all     = "arn:${local.p}:apigateway:${local.r}::/apis/*"
    api_tags     = "arn:${local.p}:apigateway:${local.r}::/tags/*"
    distribution = "arn:${local.p}:cloudfront::${local.a}:distribution/*"
    certificates = ["arn:${local.p}:acm:${local.r}:${local.a}:certificate/*", "arn:${local.p}:acm:${local.global_region}:${local.a}:certificate/*"]
  }

  # Tag conditions (INF-APPLY-3, INF-SHARED-1): both Project and Env, written exactly as the PRD tag set.
  cond_create = { for e in local.env_list : e => {
    StringEquals = { "aws:RequestTag/${local.tag_project_key}" = local.tag_project_value, "aws:RequestTag/Env" = e }
  } }
  cond_use = { for e in local.env_list : e => {
    StringEquals = { "aws:ResourceTag/${local.tag_project_key}" = local.tag_project_value, "aws:ResourceTag/Env" = e }
  } }

  act = {
    lambda_write = [
      "lambda:CreateFunction", "lambda:DeleteFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
      "lambda:PublishVersion", "lambda:CreateAlias", "lambda:UpdateAlias", "lambda:DeleteAlias",
      "lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency", "lambda:AddPermission", "lambda:RemovePermission",
      "lambda:PutFunctionEventInvokeConfig", "lambda:UpdateFunctionEventInvokeConfig", "lambda:DeleteFunctionEventInvokeConfig",
      "lambda:TagResource", "lambda:UntagResource",
    ]
    lambda_read = [
      "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionCodeSigningConfig", "lambda:GetFunctionConcurrency",
      "lambda:GetFunctionEventInvokeConfig", "lambda:GetPolicy", "lambda:GetAlias", "lambda:ListVersionsByFunction", "lambda:ListAliases", "lambda:ListTags",
    ]
    layer_write = ["lambda:PublishLayerVersion", "lambda:DeleteLayerVersion"]
    layer_read  = ["lambda:GetLayerVersion", "lambda:ListLayerVersions"]
    sfn_write = [
      "states:CreateStateMachine", "states:DeleteStateMachine", "states:UpdateStateMachine", "states:PublishStateMachineVersion",
      "states:DeleteStateMachineVersion", "states:CreateStateMachineAlias", "states:UpdateStateMachineAlias", "states:DeleteStateMachineAlias",
      "states:TagResource", "states:UntagResource",
    ]
    sfn_read = ["states:DescribeStateMachine", "states:DescribeStateMachineAlias", "states:ListStateMachineVersions", "states:ListTagsForResource"]
    ecr_write = [
      "ecr:CreateRepository", "ecr:DeleteRepository", "ecr:PutLifecyclePolicy", "ecr:DeleteLifecyclePolicy", "ecr:SetRepositoryPolicy",
      "ecr:DeleteRepositoryPolicy", "ecr:PutImageScanningConfiguration", "ecr:PutImageTagMutability", "ecr:TagResource", "ecr:UntagResource",
    ]
    ecr_read        = ["ecr:DescribeRepositories", "ecr:GetLifecyclePolicy", "ecr:GetRepositoryPolicy", "ecr:ListTagsForResource"]
    scheduler_write = ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule", "scheduler:CreateScheduleGroup", "scheduler:DeleteScheduleGroup", "scheduler:TagResource", "scheduler:UntagResource"]
    scheduler_read  = ["scheduler:GetSchedule", "scheduler:GetScheduleGroup", "scheduler:ListTagsForResource"]
    xray_write = [
      "xray:CreateGroup", "xray:UpdateGroup", "xray:DeleteGroup", "xray:CreateSamplingRule", "xray:UpdateSamplingRule", "xray:DeleteSamplingRule",
      "xray:TagResource", "xray:UntagResource",
    ]
    xray_read = ["xray:GetGroup", "xray:ListTagsForResource"]

    s3_write = [
      "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:PutBucketVersioning", "s3:PutEncryptionConfiguration",
      "s3:PutBucketPublicAccessBlock", "s3:PutBucketOwnershipControls", "s3:PutLifecycleConfiguration", "s3:PutBucketTagging", "s3:PutBucketCORS",
      "s3:PutBucketNotification", "s3:PutBucketLogging",
      # The provider creates a bucket with its tags in one call; without this it falls back to PutBucketTagging.
      "s3:TagResource",
    ]
    s3_read = [
      "s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketLocation", "s3:GetBucketPolicy", "s3:GetBucketPolicyStatus", "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration", "s3:GetBucketPublicAccessBlock", "s3:GetBucketOwnershipControls", "s3:GetLifecycleConfiguration",
      "s3:GetBucketTagging", "s3:GetBucketAcl", "s3:GetBucketCORS", "s3:GetBucketNotification", "s3:GetBucketLogging", "s3:GetBucketRequestPayment",
      "s3:GetAccelerateConfiguration", "s3:GetReplicationConfiguration", "s3:GetBucketObjectLockConfiguration", "s3:GetBucketWebsite",
    ]
    ddb_write = ["dynamodb:CreateTable", "dynamodb:DeleteTable", "dynamodb:UpdateTable", "dynamodb:UpdateTimeToLive", "dynamodb:UpdateContinuousBackups", "dynamodb:TagResource", "dynamodb:UntagResource"]
    ddb_read  = ["dynamodb:DescribeTable", "dynamodb:DescribeContinuousBackups", "dynamodb:DescribeTimeToLive", "dynamodb:DescribeKinesisStreamingDestination", "dynamodb:ListTagsOfResource"]
    kms_write = [
      "kms:EnableKeyRotation", "kms:DisableKeyRotation", "kms:PutKeyPolicy", "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion",
      "kms:UpdateKeyDescription", "kms:CreateAlias", "kms:UpdateAlias", "kms:DeleteAlias", "kms:TagResource", "kms:UntagResource",
    ]
    # Calls that AWS services make with the caller's credentials (forward access sessions) when a resource is encrypted
    # with the app key: DynamoDB (every call on the table, for example UpdateTimeToLive), Secrets Manager (CreateSecret) and S3
    # (bucket encryption). Explicit names, no wildcard: GenerateDataKey* and ReEncrypt* are spelled out.
    kms_via_service = [
      "kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlaintext",
      "kms:ReEncryptFrom", "kms:ReEncryptTo", "kms:DescribeKey",
    ]
    kms_read = ["kms:DescribeKey", "kms:GetKeyPolicy", "kms:GetKeyRotationStatus", "kms:ListResourceTags"]
    # scan-backend, 19 Nov 2026: a DynamoDB table or secret with a customer-managed key makes the service ask for a grant
    # in the caller's name. Allowed only on Graveyard keys and only for grants that an AWS service uses (kms:GrantIsForAWSResource).
    kms_grant = ["kms:CreateGrant"]
    # Exception E7 (scan-backend, approved 19 Nov 2026): CloudWatch Logs log delivery, used by Step Functions execution
    # logging and API Gateway access logs. These actions have no resource-level permissions, so the resource is *.
    # logs:PutResourcePolicy is NOT part of E7 (INF-SHARED-3 still forbids it).
    logs_delivery = [
      "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
    ]
    alias_write  = ["kms:CreateAlias", "kms:UpdateAlias", "kms:DeleteAlias"]
    ssm_write    = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:DeleteParameters", "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource"]
    ssm_read     = ["ssm:GetParameter", "ssm:GetParameters", "ssm:ListTagsForResource"]
    secret_write = ["secretsmanager:CreateSecret", "secretsmanager:DeleteSecret", "secretsmanager:UpdateSecret", "secretsmanager:RestoreSecret", "secretsmanager:TagResource", "secretsmanager:UntagResource"]
    secret_read  = ["secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy", "secretsmanager:ListSecretVersionIds"]

    apigw_read    = ["apigateway:GET"]
    cf_dist_write = ["cloudfront:UpdateDistribution", "cloudfront:DeleteDistribution", "cloudfront:TagResource", "cloudfront:UntagResource", "cloudfront:CreateInvalidation"]
    cf_dist_read  = ["cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:ListTagsForResource", "cloudfront:GetInvalidation", "cloudfront:ListInvalidations"]
    cf_fn_write   = ["cloudfront:UpdateFunction", "cloudfront:DeleteFunction", "cloudfront:PublishFunction", "cloudfront:TagResource", "cloudfront:UntagResource"]
    cf_fn_read    = ["cloudfront:DescribeFunction", "cloudfront:GetFunction", "cloudfront:ListTagsForResource"]
    waf_write = [
      "wafv2:CreateWebACL", "wafv2:UpdateWebACL", "wafv2:DeleteWebACL", "wafv2:CreateIPSet", "wafv2:UpdateIPSet", "wafv2:DeleteIPSet",
      "wafv2:CreateRuleGroup", "wafv2:UpdateRuleGroup", "wafv2:DeleteRuleGroup", "wafv2:TagResource", "wafv2:UntagResource",
    ]
    waf_read  = ["wafv2:GetWebACL", "wafv2:GetIPSet", "wafv2:GetRuleGroup", "wafv2:ListTagsForResource"]
    acm_write = ["acm:DeleteCertificate", "acm:AddTagsToCertificate", "acm:RemoveTagsFromCertificate", "acm:UpdateCertificateOptions"]
    acm_read  = ["acm:DescribeCertificate", "acm:ListTagsForCertificate"]

    logs_write = [
      "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy", "logs:TagResource", "logs:UntagResource",
      "logs:TagLogGroup", "logs:UntagLogGroup", "logs:AssociateKmsKey", "logs:DisassociateKmsKey", "logs:PutMetricFilter", "logs:DeleteMetricFilter",
    ]
    logs_read = ["logs:ListTagsForResource", "logs:ListTagsLogGroup", "logs:DescribeMetricFilters"]
    cw_write  = ["cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:PutDashboard", "cloudwatch:DeleteDashboards", "cloudwatch:TagResource", "cloudwatch:UntagResource"]
    cw_read   = ["cloudwatch:GetDashboard", "cloudwatch:ListTagsForResource"]
    syn_write = ["synthetics:CreateCanary", "synthetics:UpdateCanary", "synthetics:DeleteCanary", "synthetics:StartCanary", "synthetics:StopCanary", "synthetics:TagResource", "synthetics:UntagResource"]
    syn_read  = ["synthetics:GetCanary", "synthetics:ListTagsForResource"]
    sns_write = ["sns:CreateTopic", "sns:DeleteTopic", "sns:SetTopicAttributes", "sns:Subscribe", "sns:Unsubscribe", "sns:TagResource", "sns:UntagResource"]
    sns_read  = ["sns:GetTopicAttributes", "sns:ListTagsForResource", "sns:ListSubscriptionsByTopic"]
    br_write  = ["bedrock:UpdateGuardrail", "bedrock:DeleteGuardrail", "bedrock:CreateGuardrailVersion", "bedrock:TagResource", "bedrock:UntagResource"]
    br_read   = ["bedrock:GetGuardrail", "bedrock:ListTagsForResource"]
  }

  # Exception E8 (scan-backend, 20 Nov 2026): the Terraform AWS provider calls states:ValidateStateMachineDefinition on every
  # plan and apply that changes a state machine definition. The action has no resource-level permission and changes nothing.
  # Exception E9 (20 Nov 2026): API Gateway tags are a resource of their own, /tags/<url-encoded ARN>. CreateApi and CreateStage
  # with tags call POST on it; AWS documents no aws:RequestTag key for POST on that resource, so no tag condition is possible.
  exception_actions = {
    e8_validate = ["states:ValidateStateMachineDefinition"]
    e9_api_tags = ["apigateway:POST", "apigateway:GET", "apigateway:DELETE"]
    # Exception E10 (20 Nov 2026): Step Functions checks that the state machine role may manage log deliveries, including
    # logs:PutResourcePolicy. None of these has a resource. Allowed in the workload boundary only, and only to roles named
    # graveyard-<env>-*-sfn; never to a CI role.
    e10_sfn_logging = [
      "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
    ]
  }

  # Reads that AWS offers only on "*". Metadata only: names, ARNs and summaries, never data.
  star_reads = {
    compute = ["xray:GetSamplingRules"]
    data    = ["kms:ListAliases", "ssm:DescribeParameters"]
    edge = [
      "cloudfront:ListDistributions", "cloudfront:ListFunctions", "cloudfront:ListCachePolicies", "cloudfront:GetCachePolicy",
      "cloudfront:ListResponseHeadersPolicies", "cloudfront:GetResponseHeadersPolicy", "cloudfront:ListOriginAccessControls", "cloudfront:GetOriginAccessControl",
      "wafv2:ListWebACLs", "wafv2:ListIPSets", "wafv2:ListRuleGroups", "wafv2:ListAvailableManagedRuleGroups", "wafv2:DescribeManagedRuleGroup",
      "acm:ListCertificates",
    ]
    ops = [
      "logs:DescribeLogGroups", "cloudwatch:DescribeAlarms", "synthetics:DescribeCanaries",
      "bedrock:ListGuardrails", "bedrock:ListFoundationModels", "bedrock:ListInferenceProfiles",
    ]
  }
}
