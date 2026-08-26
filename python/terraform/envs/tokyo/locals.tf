# ============================================================================
# 東京リージョン（ACTIVE 側）の対象リソース
#
# 閉塞対象は大阪。開放系・観測系は東京を見る。
#
# 依存先の構築状況で 3 段階に分かれる。未構築でも plan / apply が通るよう、
# data ブロックごと count で制御する。try() では防げない（stateファイルが
# 読めない時点で失敗するため）。
#
#   段階 1  同一 state ＋ VPC エンドポイント   常に作れる
#           （エンドポイントは環境チームが先に作るため常に存在する）
#   段階 2  別 state の EKS クラスタ            external_eks_ready
#   段階 3  別リージョン                        peer_ready
#
# ★ リソース名と output 名は仮。実際のものに置き換えること。
# ============================================================================

locals {
  self_region = "ap-northeast-1"
  peer_region = "ap-northeast-3"

  # --- 段階 1: 同一 state --------------------------------------------------
  # API Gateway の ARN にはアカウント ID が入らない（コロンが 2 つ続く）。
  # aws_api_gateway_stage には管理用 ARN の属性が無いので組み立てる。

  self_rest_api_id = aws_api_gateway_rest_api.this.id
  self_stage_name  = aws_api_gateway_stage.this.stage_name
  self_api_arn     = "arn:aws:apigateway:${local.self_region}::/restapis/${local.self_rest_api_id}"
  self_stage_arn   = "${local.self_api_arn}/stages/${local.self_stage_name}"

  self_schedule_group     = aws_scheduler_schedule_group.this.name
  self_schedule_group_arn = aws_scheduler_schedule_group.this.arn
  self_schedule_arn       = "arn:aws:scheduler:${local.self_region}:${data.aws_caller_identity.current.account_id}:schedule/${local.self_schedule_group}/*"
  self_schedule_role_arn  = aws_iam_role.scheduler_target.arn

  self_buckets              = [for b in aws_s3_bucket.this : b.bucket]
  self_bucket_arns          = [for b in aws_s3_bucket.this : b.arn]
  self_replication_role_arn = aws_iam_role.s3_replication.arn

  self_function_names = [for f in aws_lambda_function.app : f.function_name]
  self_function_arns  = [for f in aws_lambda_function.app : f.arn]

  self_table_names = [for t in aws_dynamodb_table.this : t.name]
  self_table_arns  = [for t in aws_dynamodb_table.this : t.arn]

  self_file_system_ids  = [for f in aws_efs_file_system.this : f.id]
  self_file_system_arns = [for f in aws_efs_file_system.this : f.arn]

  self_target_group_arns  = [for g in aws_lb_target_group.this : g.arn]
  self_load_balancer_arns = [for l in aws_lb.this : l.arn]

  own_cluster = aws_eks_cluster.this

  pod_restart_function_names = [for f in aws_lambda_function.pod_restart : f.function_name]
  pod_restart_arns           = [for f in aws_lambda_function.pod_restart : f.arn]
  pod_restart_timeout        = 300

  alarm_prefix = "gems-ip-"

  # --- Route 53（カスタムドメインの切替） -----------------------------------
  # 切替は Alias レコードの向き先を変える操作。レコードは 1 つで、
  # AliasTarget.DNSName を切替先リージョンの VPC エンドポイントへ向ける。
  #
  # 切替先は「自リージョンの VPC エンドポイント」。東京の switch は東京へ、
  # 大阪の switch は大阪へ向けるので、どちらを実行するかで方向が決まる。
  #
  # プライベートホストゾーンは VPC に関連付ける。両リージョンの VPC に
  # 関連付いた 1 つのゾーンを共有する前提。別 state なら
  # terraform_remote_state から取ること。

  hosted_zone_id  = aws_route53_zone.private.zone_id
  hosted_zone_arn = "arn:aws:route53:::hostedzone/${aws_route53_zone.private.zone_id}"
  record_name     = "gems-ip.${aws_route53_zone.private.name}"

  # API Gateway の VPC エンドポイント。Alias のターゲットになる。
  self_vpce_dns_name       = tolist(aws_vpc_endpoint.execute_api.dns_entry)[0].dns_name
  self_vpce_hosted_zone_id = tolist(aws_vpc_endpoint.execute_api.dns_entry)[0].hosted_zone_id

  # --- VPC エンドポイント（別 state / output 無し） --------------------------

  interface_endpoint_security_group_ids = {
    for k, e in data.aws_vpc_endpoint.interface : k => e.security_group_ids
  }

  # --- 段階 2: 別 state の EKS クラスタ -------------------------------------

  external_eks = var.external_eks_ready ? data.terraform_remote_state.eks_external[0].outputs : null

  # --- 段階 3: 別リージョン -------------------------------------------------

  peer = var.peer_ready ? data.terraform_remote_state.peer[0].outputs : null

  peer_rest_api_id = try(local.peer.rest_api_id, null)
  peer_stage_name  = try(local.peer.stage_name, null)
  peer_stage_arn   = var.peer_ready ? "arn:aws:apigateway:${local.peer_region}::/restapis/${local.peer_rest_api_id}/stages/${local.peer_stage_name}" : null

  peer_schedule_group    = try(local.peer.schedule_group, null)
  peer_schedule_arn      = var.peer_ready ? "arn:aws:scheduler:${local.peer_region}:${data.aws_caller_identity.current.account_id}:schedule/${local.peer_schedule_group}/*" : null
  peer_schedule_role_arn = try(local.peer.schedule_role_arn, null)

  peer_buckets              = try(local.peer.replication_buckets, [])
  peer_bucket_arns          = try(local.peer.replication_bucket_arns, [])
  peer_replication_role_arn = try(local.peer.replication_role_arn, null)

  peer_endpoint_cidr_blocks = try(local.peer.endpoint_subnet_cidrs, [])

  # --- クラスタの集約 -------------------------------------------------------
  # 別 state のクラスタは external_eks_ready が false なら含めない。

  clusters = merge(
    {
      (local.own_cluster.name) = [
        {
          name = "gems-ip"
          restart_targets = [
            { kind = "Deployment", name = "alarm-receiver" },
            { kind = "Deployment", name = "master-sync" },
          ]
        },
      ]
    },
    var.external_eks_ready ? {
      (local.external_eks.cluster_name) = [{ name = "gems-ip", restart_targets = [] }]
    } : {},
  )

  self_cluster_arns = concat(
    [local.own_cluster.arn],
    var.external_eks_ready ? [local.external_eks.cluster_arn] : [],
  )

  eks_cluster_security_group_ids = merge(
    { (local.own_cluster.name) = local.own_cluster.vpc_config[0].cluster_security_group_id },
    var.external_eks_ready ? {
      (local.external_eks.cluster_name) = local.external_eks.cluster_security_group_id
    } : {},
  )

  eks_clusters_env = [
    for name, namespaces in local.clusters : { name = name, namespaces = namespaces }
  ]

  eks_view_access = [
    for name, namespaces in local.clusters : {
      cluster    = name
      policy     = "AmazonEKSViewPolicy"
      namespaces = [for n in namespaces : n.name]
    }
  ]

  eks_edit_access = [
    for name, namespaces in local.clusters : {
      cluster    = name
      policy     = "AmazonEKSEditPolicy"
      namespaces = [for n in namespaces : n.name if length(n.restart_targets) > 0]
    } if length([for n in namespaces : n if length(n.restart_targets) > 0]) > 0
  ]

  # --- エンドポイントの引き先 -----------------------------------------------
  # functions の endpoints に書いたものを自動で集める。

  endpoint_services = distinct(concat(
    ["logs"],
    flatten([for f in local.functions : f.endpoints]),
  ))
}

data "aws_caller_identity" "current" {}

# --- VPC エンドポイント ----------------------------------------------------
# 他チームが管理する VPC エンドポイント。output が無いのでサービス名で引く。
# 環境チームが先に作るため、常に存在する前提でよい。

data "aws_vpc_endpoint" "interface" {
  for_each     = toset(local.endpoint_services)
  vpc_id       = aws_vpc.this.id
  service_name = "com.amazonaws.${local.self_region}.${each.key}"
}

# 別 state の EKS クラスタ。count = 0 なら state を読みに行かない。
data "terraform_remote_state" "eks_external" {
  count   = var.external_eks_ready ? 1 : 0
  backend = "s3"
  config = {
    bucket = var.eks_external_state_bucket
    key    = var.eks_external_state_key
    region = local.self_region
  }
}

# --- 段階 3 の data --------------------------------------------------------
# 相手リージョン。東京と大阪が互いを参照するので、初回は両方 false で
# 構築し、双方が揃ってから true にする。

data "terraform_remote_state" "peer" {
  count   = var.peer_ready ? 1 : 0
  backend = "s3"
  config = {
    bucket = var.peer_state_bucket
    key    = var.peer_state_key
    region = local.peer_region
  }
}
