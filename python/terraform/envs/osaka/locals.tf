# ============================================================================
# 大阪リージョン（STANDBY 側）の対象リソース
#
# 閉塞対象は東京。開放系・観測系は大阪を見る。
#
# state の所在ごとに取り方を変える。
#
#   同一 state           リソース参照（aws_xxx.this）。依存は Terraform が解決する
#   別 state / output 有 terraform_remote_state
#   別 state / output 無 data ソース
#
# 別 state のものは**先に作られている必要がある**。これは書き方ではなく
# state が分かれていることの帰結で、どの取り方でも変わらない。
#
# ★ 以下のリソース名（aws_dynamodb_table.this など）と output 名は仮。
#   実際のものに置き換えること。
# ============================================================================

locals {
  self_region = "ap-northeast-3"
  peer_region = "ap-northeast-1"

  # --- API Gateway ---------------------------------------------------------
  # ARN にはアカウント ID が入らない（コロンが 2 つ続く）。
  # aws_api_gateway_stage には管理用 ARN の属性が無いので組み立てる。

  self_rest_api_id = aws_api_gateway_rest_api.this.id
  self_stage_name  = aws_api_gateway_stage.this.stage_name

  self_api_arn   = "arn:aws:apigateway:${local.self_region}::/restapis/${local.self_rest_api_id}"
  self_stage_arn = "${local.self_api_arn}/stages/${local.self_stage_name}"

  peer_rest_api_id = data.terraform_remote_state.peer.outputs.rest_api_id
  peer_stage_name  = data.terraform_remote_state.peer.outputs.stage_name
  peer_stage_arn   = "arn:aws:apigateway:${local.peer_region}::/restapis/${local.peer_rest_api_id}/stages/${local.peer_stage_name}"

  # --- EventBridge Scheduler -----------------------------------------------

  self_schedule_group     = aws_scheduler_schedule_group.this.name
  self_schedule_group_arn = aws_scheduler_schedule_group.this.arn
  self_schedule_arn       = "arn:aws:scheduler:${local.self_region}:${data.aws_caller_identity.current.account_id}:schedule/${local.self_schedule_group}/*"
  self_schedule_role_arn  = aws_iam_role.scheduler_target.arn

  peer_schedule_group    = data.terraform_remote_state.peer.outputs.schedule_group
  peer_schedule_arn      = "arn:aws:scheduler:${local.peer_region}:${data.aws_caller_identity.current.account_id}:schedule/${local.peer_schedule_group}/*"
  peer_schedule_role_arn = data.terraform_remote_state.peer.outputs.schedule_role_arn

  # --- S3 ------------------------------------------------------------------

  self_buckets     = [for b in aws_s3_bucket.this : b.bucket]
  self_bucket_arns = [for b in aws_s3_bucket.this : b.arn]

  peer_buckets     = data.terraform_remote_state.peer.outputs.replication_buckets
  peer_bucket_arns = data.terraform_remote_state.peer.outputs.replication_bucket_arns

  self_replication_role_arn = aws_iam_role.s3_replication.arn
  peer_replication_role_arn = data.terraform_remote_state.peer.outputs.replication_role_arn

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
  # 1 つは同一 state、1 つは別 state（output あり）。

  own_cluster      = aws_eks_cluster.this
  external_cluster = data.terraform_remote_state.eks_external.outputs

  cluster_names = [local.own_cluster.name, local.external_cluster.cluster_name]

  self_cluster_arns = [local.own_cluster.arn, local.external_cluster.cluster_arn]

  eks_cluster_security_group_ids = {
    (local.own_cluster.name)              = local.own_cluster.vpc_config[0].cluster_security_group_id
    (local.external_cluster.cluster_name) = local.external_cluster.cluster_security_group_id
  }

  # namespace と再起動対象はワークロードの定義に依存するのでここで指定する。
  clusters = {
    (local.own_cluster.name) = [
      {
        name = "gems-ip"
        restart_targets = [
          { kind = "Deployment", name = "alarm-receiver" },
          { kind = "Deployment", name = "master-sync" },
        ]
      },
    ]
    (local.external_cluster.cluster_name) = [{ name = "gems-ip", restart_targets = [] }]
  }

  eks_clusters_env = [
    for name, namespaces in local.clusters : { name = name, namespaces = namespaces }
  ]

  # アクセスポリシーの関連付け。namespace スコープで付与する。
  eks_view_access = [
    for name, namespaces in local.clusters : {
      cluster    = name
      policy     = "AmazonEKSViewPolicy"
      namespaces = [for n in namespaces : n.name]
    }
  ]

  # rollout_restart の対象がある namespace だけに Edit を付ける
  eks_edit_access = [
    for name, namespaces in local.clusters : {
      cluster    = name
      policy     = "AmazonEKSEditPolicy"
      namespaces = [for n in namespaces : n.name if length(n.restart_targets) > 0]
    } if length([for n in namespaces : n if length(n.restart_targets) > 0]) > 0
  ]

  # --- Pod 再起動（既存 Lambda を呼ぶ方式を使う場合） -----------------------

  pod_restart_function_names = [for f in aws_lambda_function.pod_restart : f.function_name]
  pod_restart_arns           = [for f in aws_lambda_function.pod_restart : f.arn]
  pod_restart_timeout        = 300

  # --- VPC エンドポイント（別 state / output 無し） --------------------------
  # data で引く。別 state で既に存在するため、これは正しい使い方。
  # 引くサービス名は functions の endpoints に書いたものと同じ。

  endpoint_services = distinct(concat(
    ["logs"],
    flatten([for f in local.functions : f.endpoints]),
  ))

  interface_endpoint_security_group_ids = {
    for k, e in data.aws_vpc_endpoint.interface : k => e.security_group_ids
  }

  # --- 相手リージョンのエンドポイント（閉塞系が使う） -----------------------
  # リージョン間 VPC ピアリングでは相手 SG を参照できないため CIDR で指定する。
  # 相手側エンドポイント SG への ingress（自 VPC CIDR からの 443）は
  # 相手リージョンの state が管理する。

  peer_endpoint_cidr_blocks = data.terraform_remote_state.peer.outputs.endpoint_subnet_cidrs

  # --- その他 --------------------------------------------------------------

  alarm_prefix = "gems-ip-"
}

# scheduler の ARN 組み立てにのみ使う。他はリソース参照または output から取る。
data "aws_caller_identity" "current" {}

# 別 state（output あり）
data "terraform_remote_state" "peer" {
  backend = "s3"
  config = {
    bucket = var.peer_state_bucket
    key    = var.peer_state_key
    region = local.peer_region
  }
}

data "terraform_remote_state" "eks_external" {
  backend = "s3"
  config = {
    bucket = var.eks_external_state_bucket
    key    = var.eks_external_state_key
    region = local.self_region
  }
}

# 別 state（output 無し）。サービス名で引く。
data "aws_vpc_endpoint" "interface" {
  for_each     = toset(local.endpoint_services)
  vpc_id       = aws_vpc.this.id
  service_name = "com.amazonaws.${local.self_region}.${each.key}"
}
