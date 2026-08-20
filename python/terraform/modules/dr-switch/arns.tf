# ============================================================================
# ARN の組み立て
#
# 対象リソースの ID を変数で受け取り、ARN を文字列として組み立てる。
# 同一 state でリソースを管理しているなら、変数へリソース参照を渡すこと
# （例: rest_api_id = aws_api_gateway_rest_api.this.id）。
# ============================================================================

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # API Gateway の ARN にはアカウント ID が入らない（コロンが 2 つ続く）
  self_api_arn   = "arn:aws:apigateway:${var.self_region}::/restapis/${var.self_rest_api_id}"
  self_stage_arn = "${local.self_api_arn}/stages/${var.self_stage}"
  peer_stage_arn = "arn:aws:apigateway:${var.peer_region}::/restapis/${var.peer_rest_api_id}/stages/${var.peer_stage}"

  self_schedule_arn       = "arn:aws:scheduler:${var.self_region}:${local.account_id}:schedule/${var.self_schedule_group}/*"
  peer_schedule_arn       = "arn:aws:scheduler:${var.peer_region}:${local.account_id}:schedule/${var.peer_schedule_group}/*"
  self_schedule_group_arn = "arn:aws:scheduler:${var.self_region}:${local.account_id}:schedule-group/${var.self_schedule_group}"

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
    for c in var.eks_clusters :
    "arn:aws:eks:${var.self_region}:${local.account_id}:cluster/${c.name}"
  ]
  pod_restart_arns = [
    for n in var.pod_restart_function_names :
    "arn:aws:lambda:${var.self_region}:${local.account_id}:function:${n}"
  ]
}
