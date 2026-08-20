# ============================================================================
# 大阪リージョン（STANDBY 側）の対象リソース
#
# 同一 state で管理しているリソースは**リソース参照から取る**。名前を直値で
# 書くと、リソース名を変えたときに権限がズレる。タイプミスも plan では
# 検出されず、実行時の権限エラーになるまで気づけない。
#
# ARN も文字列で組み立てない。参照から取れば、フォーマットを間違える余地が
# 無くなる。
#
# ★ 以下のリソース名（aws_dynamodb_table.this など）は仮。実際の名前に
#   置き換えること。相手リージョン（peer_*）のリソースは別 state なので
#   terraform_remote_state か変数で受け取る。
# ============================================================================

locals {
  self_region = "ap-northeast-3"
  peer_region = "ap-northeast-1"

  # --- API Gateway ---------------------------------------------------------
  # ARN にはアカウント ID が入らない（コロンが 2 つ続く）ため、
  # stage リソースの ARN 属性ではなく execution_arn とも別物になる。
  # aws_api_gateway_stage には管理用 ARN の属性が無いので、rest_api の id と
  # stage_name から組み立てる。

  self_rest_api_id = aws_api_gateway_rest_api.this.id
  self_stage_name  = aws_api_gateway_stage.this.stage_name

  self_api_arn   = "arn:aws:apigateway:${local.self_region}::/restapis/${local.self_rest_api_id}"
  self_stage_arn = "${local.self_api_arn}/stages/${local.self_stage_name}"

  peer_rest_api_id = var.peer_rest_api_id
  peer_stage_name  = var.peer_stage_name
  peer_stage_arn   = "arn:aws:apigateway:${local.peer_region}::/restapis/${local.peer_rest_api_id}/stages/${local.peer_stage_name}"

  # --- EventBridge Scheduler -----------------------------------------------

  self_schedule_group     = aws_scheduler_schedule_group.this.name
  self_schedule_group_arn = aws_scheduler_schedule_group.this.arn
  self_schedule_arn       = "arn:aws:scheduler:${local.self_region}:${data.aws_caller_identity.current.account_id}:schedule/${local.self_schedule_group}/*"
  self_schedule_role_arn  = aws_iam_role.scheduler_target.arn

  peer_schedule_group    = var.peer_schedule_group
  peer_schedule_arn      = var.peer_schedule_arn
  peer_schedule_role_arn = var.peer_schedule_role_arn

  # --- S3 ------------------------------------------------------------------

  self_buckets     = [for b in aws_s3_bucket.this : b.bucket]
  self_bucket_arns = [for b in aws_s3_bucket.this : b.arn]

  peer_buckets     = var.peer_replication_buckets
  peer_bucket_arns = var.peer_replication_bucket_arns

  self_replication_role_arn = aws_iam_role.s3_replication.arn
  peer_replication_role_arn = var.peer_replication_role_arn

  # --- Lambda / DynamoDB / EFS ---------------------------------------------

  self_function_names = [for f in aws_lambda_function.app : f.function_name]
  self_function_arns  = [for f in aws_lambda_function.app : f.arn]

  self_table_names = [for t in aws_dynamodb_table.this : t.name]
  self_table_arns  = [for t in aws_dynamodb_table.this : t.arn]

  self_file_system_ids  = [for f in aws_efs_file_system.this : f.id]
  self_file_system_arns = [for f in aws_efs_file_system.this : f.arn]

  # --- NLB -----------------------------------------------------------------

  self_target_group_arns  = [for g in aws_lb_target_group.this : g.arn]
  self_load_balancer_arns = [for l in aws_lb.this : l.arn]

  # --- EKS -----------------------------------------------------------------

  cluster_names = [for c in aws_eks_cluster.this : c.name]
  self_cluster_arns = [for c in aws_eks_cluster.this : c.arn]

  eks_cluster_security_group_ids = {
    for k, c in aws_eks_cluster.this :
    c.name => c.vpc_config[0].cluster_security_group_id
  }

  # dr_switch の EKS_CLUSTERS にそのまま渡す形。
  # namespace と再起動対象はワークロードの定義に依存するのでここで指定する。
  clusters = {
    (aws_eks_cluster.this["a"].name) = [
      {
        name = "gems-ip"
        restart_targets = [
          { kind = "Deployment", name = "alarm-receiver" },
          { kind = "Deployment", name = "master-sync" },
        ]
      },
    ]
    (aws_eks_cluster.this["b"].name) = [{ name = "gems-ip", restart_targets = [] }]
  }

  eks_clusters_env = [
    for name, namespaces in local.clusters : { name = name, namespaces = namespaces }
  ]

  # --- Pod 再起動（既存 Lambda を呼ぶ方式を使う場合） -----------------------

  pod_restart_function_names = [for f in aws_lambda_function.pod_restart : f.function_name]
  pod_restart_arns           = [for f in aws_lambda_function.pod_restart : f.arn]
  pod_restart_timeout        = 300

  # --- その他 --------------------------------------------------------------

  alarm_prefix = "gems-ip-"

  # 別 state のインターフェースエンドポイント。サービス名 -> SG ID。
  interface_endpoint_security_group_ids = var.interface_endpoint_security_group_ids
}

# scheduler の ARN 組み立てにのみ使う。他はリソース参照から取る。
data "aws_caller_identity" "current" {}
