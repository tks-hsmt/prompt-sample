# ============================================================================
# 大阪リージョン（STANDBY 側）の対象リソース
#
# ここと functions.tf だけが環境ごとに変わる。module 側は入力に従って作る。
# 同一 state で対象リソースを管理しているなら、名前ではなくリソース参照から
# ARN を取ること（例: [for t in aws_dynamodb_table.this : t.arn]）。
# ============================================================================

data "aws_caller_identity" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  self_region = "ap-northeast-3"
  peer_region = "ap-northeast-1"

  # --- 対象リソースの識別子 -------------------------------------------------

  self_api    = { id = var.self_rest_api_id, stage = "prod" }
  peer_api    = { id = var.peer_rest_api_id, stage = "prod" }
  self_group  = "gems-ip"
  peer_group  = "gems-ip"
  self_buckets = ["gems-ip-osaka"]
  peer_buckets = ["gems-ip-tokyo"]

  self_function_names  = ["gems-ip-alarm-router", "gems-ip-master-sync"]
  self_table_names     = ["gems-ip-inventory", "gems-ip-device", "gems-ip-snmpyml"]
  self_file_system_ids = ["fs-0123456789abcdef0"]
  alarm_prefix         = "gems-ip-"

  pod_restart_function_names = []
  pod_restart_timeout        = 300

  clusters = {
    "osaka-cluster-a" = [
      {
        name = "gems-ip"
        restart_targets = [
          { kind = "Deployment", name = "alarm-receiver" },
          { kind = "Deployment", name = "master-sync" },
        ]
      },
    ]
    "osaka-cluster-b" = [{ name = "gems-ip", restart_targets = [] }]
  }

  # --- ARN の組み立て -------------------------------------------------------
  # API Gateway の ARN にはアカウント ID が入らない（コロンが 2 つ続く）

  self_api_arn   = "arn:aws:apigateway:${local.self_region}::/restapis/${local.self_api.id}"
  self_stage_arn = "${local.self_api_arn}/stages/${local.self_api.stage}"
  peer_stage_arn = "arn:aws:apigateway:${local.peer_region}::/restapis/${local.peer_api.id}/stages/${local.peer_api.stage}"

  self_schedule_arn       = "arn:aws:scheduler:${local.self_region}:${local.account_id}:schedule/${local.self_group}/*"
  peer_schedule_arn       = "arn:aws:scheduler:${local.peer_region}:${local.account_id}:schedule/${local.peer_group}/*"
  self_schedule_group_arn = "arn:aws:scheduler:${local.self_region}:${local.account_id}:schedule-group/${local.self_group}"

  self_bucket_arns = [for b in local.self_buckets : "arn:aws:s3:::${b}"]
  peer_bucket_arns = [for b in local.peer_buckets : "arn:aws:s3:::${b}"]

  self_function_arns = [for n in local.self_function_names :
  "arn:aws:lambda:${local.self_region}:${local.account_id}:function:${n}"]
  self_table_arns = [for n in local.self_table_names :
  "arn:aws:dynamodb:${local.self_region}:${local.account_id}:table/${n}"]
  self_file_system_arns = [for i in local.self_file_system_ids :
  "arn:aws:elasticfilesystem:${local.self_region}:${local.account_id}:file-system/${i}"]
  self_cluster_arns = [for name, _ in local.clusters :
  "arn:aws:eks:${local.self_region}:${local.account_id}:cluster/${name}"]
  pod_restart_arns = [for n in local.pod_restart_function_names :
  "arn:aws:lambda:${local.self_region}:${local.account_id}:function:${n}"]

  # dr_switch の EKS_CLUSTERS にそのまま渡す形
  eks_clusters_env = [
    for name, namespaces in local.clusters : { name = name, namespaces = namespaces }
  ]
}
