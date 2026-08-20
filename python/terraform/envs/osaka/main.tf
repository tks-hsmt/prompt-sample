# ============================================================================
# 大阪リージョン（STANDBY 側）
#
# 閉塞対象は東京。開放系・観測系は大阪を見る。
# self / peer が東京側と逆になるだけで、module の構造は同じ。
# ============================================================================

locals {
  self_region = "ap-northeast-3"
  peer_region = "ap-northeast-1"

  cluster_a = "osaka-cluster-a"
  cluster_b = "osaka-cluster-b"

  eks_clusters = [
    {
      name = local.cluster_a
      namespaces = [
        {
          name = "gems-ip"
          restart_targets = [
            { kind = "Deployment", name = "alarm-receiver" },
            { kind = "Deployment", name = "master-sync" },
          ]
        },
      ]
    },
    {
      name       = local.cluster_b
      namespaces = [{ name = "gems-ip" }]
    },
  ]
}

module "dr_switch" {
  source = "../../modules/dr-switch"

  self_region = local.self_region
  peer_region = local.peer_region

  # API Gateway
  self_rest_api_id = var.self_rest_api_id
  self_stage       = "prod"
  peer_rest_api_id = var.peer_rest_api_id
  peer_stage       = "prod"

  # EventBridge Scheduler
  self_schedule_group    = "gems-ip"
  peer_schedule_group    = "gems-ip"
  self_schedule_role_arn = var.self_schedule_role_arn
  peer_schedule_role_arn = var.peer_schedule_role_arn

  # S3（案 A を採る場合のみ値を入れる）
  self_replication_buckets  = ["gems-ip-osaka"]
  peer_replication_buckets  = ["gems-ip-tokyo"]
  self_replication_role_arn = var.self_replication_role_arn
  peer_replication_role_arn = var.peer_replication_role_arn

  # 観測対象
  self_function_names     = ["gems-ip-alarm-router", "gems-ip-master-sync"]
  self_table_names        = ["gems-ip-inventory", "gems-ip-device", "gems-ip-snmpyml"]
  self_file_system_ids    = ["fs-0123456789abcdef0"]
  self_target_group_arns  = var.self_target_group_arns
  self_load_balancer_arns = var.self_load_balancer_arns
  alarm_prefix            = "gems-ip-"

  # EKS
  eks_clusters = local.eks_clusters

  # Pod 再起動（既存 Lambda を呼ぶ方式を使う場合）
  pod_restart_function_names = []
  pod_restart_timeout        = 300

  # ネットワーク
  vpc_id                                = var.vpc_id
  vpc_subnet_ids                        = var.vpc_subnet_ids
  interface_endpoint_security_group_ids = var.interface_endpoint_security_group_ids
  eks_cluster_security_group_ids        = var.eks_cluster_security_group_ids

  image_uri = var.image_uri
}

# --- Kubernetes RBAC（クラスタごとに 1 回） ---------------------------------

module "rbac_cluster_a" {
  source    = "../../modules/dr-switch-rbac"
  providers = { kubernetes = kubernetes.cluster_a }

  namespaces = module.dr_switch.cluster_namespaces[local.cluster_a]
  rbac_group = module.dr_switch.rbac_group
}

module "rbac_cluster_b" {
  source    = "../../modules/dr-switch-rbac"
  providers = { kubernetes = kubernetes.cluster_b }

  namespaces = module.dr_switch.cluster_namespaces[local.cluster_b]
  rbac_group = module.dr_switch.rbac_group
}

output "function_arns" {
  value = module.dr_switch.function_arns
}
