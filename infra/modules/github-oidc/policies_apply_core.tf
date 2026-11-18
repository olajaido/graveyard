# Apply role policies, part 1: state access, IAM, and the explicit denies (INF-APPLY-1, INF-APPLY-4..6,
# INF-REG-2, design 5.2.3 to 5.2.5). Explicit action lists only: no wildcard in an Allow action.
locals {
  all_envs = ["dev", "prod"]

  # Workload roles and policies of an env sit on /graveyard-<env>/ and are named graveyard-<env>-*.
  workload_role   = { for e in local.env_list : e => "arn:${local.p}:iam::${local.a}:role/graveyard-${e}/graveyard-${e}-*" }
  workload_policy = { for e in local.env_list : e => "arn:${local.p}:iam::${local.a}:policy/graveyard-${e}/graveyard-${e}-*" }
  other_envs      = { for e in local.env_list : e => [for o in local.all_envs : o if o != e] }

  passable_services = ["lambda.amazonaws.com", "states.amazonaws.com", "scheduler.amazonaws.com", "apigateway.amazonaws.com", "synthetics.amazonaws.com"]

  apply_core_docs = { for e in local.env_list : e => {
    state = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Sid      = "ListOwnState"
          Effect   = "Allow"
          Action   = ["s3:ListBucket"]
          Resource = [local.arn.state_bucket]
          Condition = {
            StringLike = { "s3:prefix" = ["envs/${e}/*", "plans/*"] }
          }
        },
        {
          Sid      = "OwnStateKey"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject"]
          Resource = [local.state_object[e]]
        },
        {
          Sid      = "OwnLockKey"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = [local.lock_object[e]]
        },
        {
          # Saved plans are named plans/<run id>/<env>.tfplan, so the env is the last part of the key.
          Sid      = "ReadOwnPlans"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:GetObjectVersion"]
          Resource = ["${local.arn.state_bucket}/plans/*/${e}.tfplan"]
        },
        {
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

    iam = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          # INF-APPLY-4: a workload role is created only under this env's path and name, and only with this env's boundary.
          Sid      = "CreateWorkloadRoles"
          Effect   = "Allow"
          Action   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
          Resource = [local.workload_role[e]]
          Condition = {
            StringEquals = { "iam:PermissionsBoundary" = local.boundary_arn[e] }
          }
        },
        {
          Sid    = "ManageWorkloadRoles"
          Effect = "Allow"
          Action = [
            "iam:GetRole", "iam:UpdateRole", "iam:UpdateRoleDescription", "iam:DeleteRole", "iam:TagRole", "iam:UntagRole",
            "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
            "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole", "iam:ListRoleTags",
          ]
          Resource = [local.workload_role[e]]
        },
        {
          # Only this env's own policies can be attached: an AWS managed policy such as AdministratorAccess cannot.
          Sid      = "AttachOnlyOwnPolicies"
          Effect   = "Allow"
          Action   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
          Resource = [local.workload_role[e]]
          Condition = {
            ArnLike = { "iam:PolicyARN" = local.workload_policy[e] }
          }
        },
        {
          Sid    = "ManageWorkloadPolicies"
          Effect = "Allow"
          Action = [
            "iam:CreatePolicy", "iam:DeletePolicy", "iam:CreatePolicyVersion", "iam:DeletePolicyVersion",
            "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions", "iam:TagPolicy", "iam:UntagPolicy", "iam:ListPolicyTags",
          ]
          Resource = [local.workload_policy[e]]
        },
        {
          Sid      = "PassWorkloadRoles"
          Effect   = "Allow"
          Action   = ["iam:PassRole"]
          Resource = [local.workload_role[e]]
          Condition = {
            StringEquals = { "iam:PassedToService" = local.passable_services }
          }
        },
      ]
    })

    guard = jsonencode({
      Version = "2012-10-17"
      Statement = concat(
        [
          {
            # INF-APPLY-1: the CI roles, their policies and the OIDC provider are never changed by CI,
            # whether or not this stack created the provider (INF-OIDC-10).
            Sid      = "DenyCiIdentity"
            Effect   = "Deny"
            Action   = ["iam:*"]
            Resource = ["${local.arn.ci_roles}*", "${local.arn.ci_policies}*", local.arn.oidc]
          },
          {
            # INF-APPLY-5
            Sid    = "DenyIdentityCreation"
            Effect = "Deny"
            Action = [
              "iam:CreateUser", "iam:CreateGroup", "iam:CreateAccessKey", "iam:CreateLoginProfile",
              "iam:CreateOpenIDConnectProvider", "iam:CreateSAMLProvider",
              "iam:DeleteRolePermissionsBoundary", "iam:DeleteUserPermissionsBoundary",
            ]
            Resource = "*"
          },
          {
            Sid    = "DenyStateConfig"
            Effect = "Deny"
            Action = [
              "s3:PutBucket*", "s3:DeleteBucket*", "s3:PutLifecycleConfiguration", "s3:PutEncryptionConfiguration",
              "s3:PutBucketPolicy", "s3:DeleteObjectVersion",
            ]
            Resource = [local.arn.state_bucket, "${local.arn.state_bucket}/*"]
          },
          {
            Sid    = "DenyOtherState"
            Effect = "Deny"
            Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"]
            Resource = concat(
              ["${local.arn.state_bucket}/bootstrap/*"],
              [for o in local.other_envs[e] : "${local.arn.state_bucket}/envs/${o}/*"],
              [for o in local.other_envs[e] : "${local.arn.state_bucket}/plans/*/${o}.tfplan"],
            )
          },
          {
            Sid       = "DenyStateKeyAdmin"
            Effect    = "Deny"
            NotAction = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
            Resource  = [local.arn.state_key]
          },
          {
            # C3: everything that is named for the other env is out of reach, even where an Allow had to use "*".
            Sid    = "DenyOtherEnv"
            Effect = "Deny"
            Action = ["*"]
            Resource = flatten([for o in local.other_envs[e] : [
              "arn:${local.p}:*:*:*:*graveyard-${o}-*",
              "arn:${local.p}:*:*:*:*graveyard/${o}/*",
            ]])
          },
          {
            Sid       = "DenyOtherEnvTag"
            Effect    = "Deny"
            Action    = ["*"]
            Resource  = "*"
            Condition = { StringEquals = { "aws:ResourceTag/Env" = local.other_envs[e] } }
          },
          {
            Sid      = "DenyCost"
            Effect   = "Deny"
            Action   = ["budgets:*", "ce:*"]
            Resource = "*"
          },
          {
            # Secret containers are managed here; their values never are (design 5.2.3).
            Sid      = "DenySecretValues"
            Effect   = "Deny"
            Action   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
            Resource = "*"
          },
        ],
        local.region_deny,
      )
    })
  } }
}
