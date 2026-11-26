# Plan role policies (INF-PLAN-1..4, design 5.2.2). The plan role can be used from a pull-request
# branch (accepted risk O8), so it reads configuration but never data (no table items, no objects
# outside the state bucket, no secret values).
locals {
  plan_policies = {
    "graveyard-plan-state" = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Sid      = "ListStateBucket"
          Effect   = "Allow"
          Action   = ["s3:ListBucket"]
          Resource = [local.arn.state_bucket]
          Condition = {
            StringLike = { "s3:prefix" = concat([for e in local.env_list : "envs/${e}/*"], ["plans/*"]) }
          }
        },
        {
          Sid      = "ReadStateAndLocks"
          Effect   = "Allow"
          Action   = ["s3:GetObject"]
          Resource = concat([for e in local.env_list : local.state_object[e]], [for e in local.env_list : local.lock_object[e]])
        },
        {
          # use_lockfile = true writes and deletes <key>.tflock during a plan (INF-PLAN-3).
          Sid      = "WriteLockKeys"
          Effect   = "Allow"
          Action   = ["s3:PutObject", "s3:DeleteObject"]
          Resource = [for e in local.env_list : local.lock_object[e]]
        },
        {
          Sid      = "WritePlans"
          Effect   = "Allow"
          Action   = ["s3:PutObject"]
          Resource = ["${local.arn.state_bucket}/plans/*"]
        },
        {
          # SSE-KMS objects need the key. The key carries the Project tag through default_tags (INF-SHARED-1).
          Sid      = "UseStateKey"
          Effect   = "Allow"
          Action   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
          Resource = [local.arn.state_key]
          Condition = {
            StringEquals = {
              "kms:ViaService"                           = "s3.${local.r}.amazonaws.com"
              "aws:ResourceTag/${local.tag_project_key}" = local.tag_project_value
            }
          }
        },
      ]
    })

    # Placeholder for the IAM reads that need no scoping decision. T9 adds the other read policies
    # (compute, data, edge, ops) from the scoping matrix of design 5.2.3.
    "graveyard-plan-read-iam" = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Sid      = "ReadWorkloadRoles"
          Effect   = "Allow"
          Action   = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListRoleTags", "iam:ListInstanceProfilesForRole"]
          Resource = [for e in local.env_list : "arn:${local.p}:iam::${local.a}:role/graveyard-${e}/graveyard-${e}-*"]
        },
        {
          Sid      = "ReadWorkloadPolicies"
          Effect   = "Allow"
          Action   = ["iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions", "iam:ListPolicyTags"]
          Resource = [for e in local.env_list : "arn:${local.p}:iam::${local.a}:policy/graveyard-${e}/graveyard-${e}-*"]
        },
      ]
    })

    "graveyard-plan-guard" = jsonencode({
      Version = "2012-10-17"
      Statement = concat(
        [
          {
            Sid      = "DenySecretValues"
            Effect   = "Deny"
            Action   = ["secretsmanager:GetSecretValue"]
            Resource = "*"
          },
          {
            Sid         = "DenyDecryptOutsideStateKey"
            Effect      = "Deny"
            Action      = ["kms:Decrypt"]
            NotResource = [local.arn.state_key]
          },
          {
            Sid         = "DenyObjectReadOutsideStateBucket"
            Effect      = "Deny"
            Action      = ["s3:GetObject", "s3:GetObjectVersion"]
            NotResource = ["${local.arn.state_bucket}/*"]
          },
          {
            # INF-PLAN-4: the plan role never reads or writes the bootstrap state.
            Sid      = "DenyBootstrapState"
            Effect   = "Deny"
            Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"]
            Resource = ["${local.arn.state_bucket}/bootstrap/*"]
          },
        ],
        local.region_deny_ci,
      )
    })
  }
}
