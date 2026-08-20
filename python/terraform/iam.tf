# ============================================================================
# 各 Lambda の実行ロールと最小権限
#
# 権限一覧（16 関数）
#
#   関数                       アクション                              Resource
#   -------------------------  --------------------------------------  --------
#   apigateway-block           apigateway:GET / PATCH                  PEER ステージ
#   apigateway-enable          apigateway:GET / PATCH                  SELF ステージ
#   apigateway-check           apigateway:GET                          SELF API + ステージ
#   scheduler-block            scheduler:List/Get/UpdateSchedule       PEER グループ
#                              iam:PassRole                            PEER 実行ロール
#   scheduler-enable           同上                                    SELF
#   scheduler-check            scheduler:GetScheduleGroup/ListSchedules SELF グループ
#   s3-block                   s3:Get/PutReplicationConfiguration      PEER バケット
#                              iam:PassRole                            PEER レプリケーションロール
#   s3-enable                  同上                                    SELF
#   s3-check                   s3:GetReplicationConfiguration          SELF バケット
#   lambda-check               lambda:GetFunctionConfiguration         SELF 対象関数
#   dynamodb-check             dynamodb:DescribeTable                  SELF 対象テーブル
#   nlb-check                  elasticloadbalancing:Describe*          *（下記注記）
#   cloudwatch-check           cloudwatch:DescribeAlarms               *（下記注記）
#   efs-check                  elasticfilesystem:Describe*             SELF ファイルシステム
#   eks-check                  eks:DescribeCluster / sts:GetCallerIdentity
#   eks-rollout-restart        同上（＋ Kubernetes RBAC の patch）
#   eks-restart-pods           lambda:InvokeFunction                   再起動関数
#
# Resource を "*" にせざるを得ないもの:
#   - elasticloadbalancing:Describe*  … リソースレベル権限に非対応。
#     AWS のマネージドポリシー AmazonECSInfrastructureRolePolicyForLoadBalancers
#     でも Describe 系だけ "*"、RegisterTargets 等は ARN 指定になっている
#   - cloudwatch:DescribeAlarms       … 同上
#   - sts:GetCallerIdentity           … 同上
# ============================================================================

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # API Gateway の ARN にはアカウント ID が入らない（コロンが 2 つ続く）
  self_api_arn   = "arn:aws:apigateway:${var.self_region}::/restapis/${var.self_rest_api_id}"
  self_stage_arn = "${local.self_api_arn}/stages/${var.self_stage}"
  peer_stage_arn = "arn:aws:apigateway:${var.peer_region}::/restapis/${var.peer_rest_api_id}/stages/${var.peer_stage}"

  self_schedule_arns = ["arn:aws:scheduler:${var.self_region}:${local.account_id}:schedule/${var.self_schedule_group}/*"]
  peer_schedule_arns = ["arn:aws:scheduler:${var.peer_region}:${local.account_id}:schedule/${var.peer_schedule_group}/*"]
  self_group_arn     = "arn:aws:scheduler:${var.self_region}:${local.account_id}:schedule-group/${var.self_schedule_group}"

  self_bucket_arns = [for b in var.self_replication_buckets : "arn:aws:s3:::${b}"]
  peer_bucket_arns = [for b in var.peer_replication_buckets : "arn:aws:s3:::${b}"]

  self_function_arns = [
    for n in var.self_function_names :
    "arn:aws:lambda:${var.self_region}:${local.account_id}:function:${n}"
  ]
  self_table_arns = [
    for n in var.self_table_names :
    "arn:aws:dynamodb:${var.self_region}:${local.account_id}:table/${n}"
  ]
  self_file_system_arns = [
    for i in var.self_file_system_ids :
    "arn:aws:elasticfilesystem:${var.self_region}:${local.account_id}:file-system/${i}"
  ]
  self_cluster_arns = [
    for n in var.self_cluster_names :
    "arn:aws:eks:${var.self_region}:${local.account_id}:cluster/${n}"
  ]
  pod_restart_arns = [
    for n in var.pod_restart_function_names :
    "arn:aws:lambda:${var.self_region}:${local.account_id}:function:${n}"
  ]
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# --- API Gateway -----------------------------------------------------------

data "aws_iam_policy_document" "apigateway_block" {
  statement {
    # aws apigateway get-stage / update-stage
    actions   = ["apigateway:GET", "apigateway:PATCH"]
    resources = [local.peer_stage_arn]
  }
}

data "aws_iam_policy_document" "apigateway_enable" {
  statement {
    actions   = ["apigateway:GET", "apigateway:PATCH"]
    resources = [local.self_stage_arn]
  }
}

data "aws_iam_policy_document" "apigateway_check" {
  statement {
    # get-rest-api（apiStatus）と get-stage（スロットリング値）で対象が違う
    actions   = ["apigateway:GET"]
    resources = [local.self_api_arn, local.self_stage_arn]
  }
}

# --- EventBridge Scheduler -------------------------------------------------

data "aws_iam_policy_document" "scheduler_block" {
  statement {
    actions = [
      "scheduler:ListSchedules",
      "scheduler:GetSchedule",
      "scheduler:UpdateSchedule",
    ]
    resources = local.peer_schedule_arns
  }
  statement {
    # UpdateSchedule は Target.RoleArn を含む全パラメータを要求するため必須
    actions   = ["iam:PassRole"]
    resources = [var.peer_schedule_role_arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["scheduler.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "scheduler_enable" {
  statement {
    actions = [
      "scheduler:ListSchedules",
      "scheduler:GetSchedule",
      "scheduler:UpdateSchedule",
    ]
    resources = local.self_schedule_arns
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [var.self_schedule_role_arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["scheduler.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "scheduler_check" {
  statement {
    actions   = ["scheduler:GetScheduleGroup"]
    resources = [local.self_group_arn]
  }
  statement {
    actions   = ["scheduler:ListSchedules"]
    resources = local.self_schedule_arns
  }
}

# --- S3 --------------------------------------------------------------------
# 案 A（切替時にトグル）を採る場合のみ block / enable をデプロイする。
# バケットは SSE-S3（AES256）なので KMS 関連の権限は不要。

data "aws_iam_policy_document" "s3_block" {
  statement {
    actions = [
      "s3:GetReplicationConfiguration",
      "s3:PutReplicationConfiguration",
    ]
    resources = local.peer_bucket_arns
  }
  dynamic "statement" {
    for_each = var.peer_replication_role_arn == null ? [] : [1]
    content {
      actions   = ["iam:PassRole"]
      resources = [var.peer_replication_role_arn]
      condition {
        test     = "StringEquals"
        variable = "iam:PassedToService"
        values   = ["s3.amazonaws.com"]
      }
    }
  }
}

data "aws_iam_policy_document" "s3_enable" {
  statement {
    actions = [
      "s3:GetReplicationConfiguration",
      "s3:PutReplicationConfiguration",
    ]
    resources = local.self_bucket_arns
  }
  dynamic "statement" {
    for_each = var.self_replication_role_arn == null ? [] : [1]
    content {
      actions   = ["iam:PassRole"]
      resources = [var.self_replication_role_arn]
      condition {
        test     = "StringEquals"
        variable = "iam:PassedToService"
        values   = ["s3.amazonaws.com"]
      }
    }
  }
}

data "aws_iam_policy_document" "s3_check" {
  statement {
    actions   = ["s3:GetReplicationConfiguration"]
    resources = local.self_bucket_arns
  }
}

# --- Lambda / DynamoDB -----------------------------------------------------

data "aws_iam_policy_document" "lambda_check" {
  statement {
    # GetFunction ではなく GetFunctionConfiguration。応答が軽く権限も狭い
    actions   = ["lambda:GetFunctionConfiguration"]
    resources = local.self_function_arns
  }
}

data "aws_iam_policy_document" "dynamodb_check" {
  statement {
    actions   = ["dynamodb:DescribeTable"]
    resources = local.self_table_arns
  }
}

# --- NLB / CloudWatch ------------------------------------------------------
# どちらもリソースレベル権限に非対応のため "*" になる。

data "aws_iam_policy_document" "nlb_check" {
  statement {
    actions = [
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeTargetHealth",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "cloudwatch_check" {
  statement {
    actions   = ["cloudwatch:DescribeAlarms"]
    resources = ["*"]
  }
}

# --- EFS -------------------------------------------------------------------

data "aws_iam_policy_document" "efs_check" {
  statement {
    actions = [
      "elasticfilesystem:DescribeFileSystems",
      "elasticfilesystem:DescribeMountTargets",
    ]
    resources = local.self_file_system_arns
  }
}

# --- EKS -------------------------------------------------------------------
# Pod / Deployment の参照・更新権限は IAM ではなく Kubernetes RBAC 側で付与する
# （下の access_entry.tf を参照）。IAM 側は kubeconfig 生成に必要な分だけ。

data "aws_iam_policy_document" "eks_access" {
  statement {
    actions   = ["eks:DescribeCluster"]
    resources = local.self_cluster_arns
  }
  statement {
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "eks_restart_pods" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = local.pod_restart_arns
  }
}

# --- ロールとポリシーの生成 -------------------------------------------------

locals {
  # 関数名 -> ポリシー JSON
  policies = {
    "apigateway-block"    = data.aws_iam_policy_document.apigateway_block.json
    "apigateway-enable"   = data.aws_iam_policy_document.apigateway_enable.json
    "apigateway-check"    = data.aws_iam_policy_document.apigateway_check.json
    "scheduler-block"     = data.aws_iam_policy_document.scheduler_block.json
    "scheduler-enable"    = data.aws_iam_policy_document.scheduler_enable.json
    "scheduler-check"     = data.aws_iam_policy_document.scheduler_check.json
    "s3-block"            = data.aws_iam_policy_document.s3_block.json
    "s3-enable"           = data.aws_iam_policy_document.s3_enable.json
    "s3-check"            = data.aws_iam_policy_document.s3_check.json
    "lambda-check"        = data.aws_iam_policy_document.lambda_check.json
    "dynamodb-check"      = data.aws_iam_policy_document.dynamodb_check.json
    "nlb-check"           = data.aws_iam_policy_document.nlb_check.json
    "cloudwatch-check"    = data.aws_iam_policy_document.cloudwatch_check.json
    "efs-check"           = data.aws_iam_policy_document.efs_check.json
    "eks-check"           = data.aws_iam_policy_document.eks_access.json
    "eks-rollout-restart" = data.aws_iam_policy_document.eks_access.json
    "eks-restart-pods"    = data.aws_iam_policy_document.eks_restart_pods.json
  }

  # 全関数を VPC 内に配置する方針のため、ENI の作成・削除権限も全関数に要る。
  vpc_functions = keys(local.policies)
}

resource "aws_iam_role" "dr" {
  for_each           = local.policies
  name               = "dr-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "dr" {
  for_each = local.policies
  name     = "dr-${each.key}"
  role     = aws_iam_role.dr[each.key].id
  policy   = each.value
}

# CloudWatch Logs への書き込み。全関数に必要。
resource "aws_iam_role_policy_attachment" "basic" {
  for_each   = local.policies
  role       = aws_iam_role.dr[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC 配置する関数には ENI の作成・削除権限が要る。全関数が対象。
resource "aws_iam_role_policy_attachment" "vpc" {
  for_each   = toset(local.vpc_functions)
  role       = aws_iam_role.dr[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

output "role_arns" {
  description = "Lambda 定義から参照する実行ロール"
  value       = { for k, r in aws_iam_role.dr : k => r.arn }
}
