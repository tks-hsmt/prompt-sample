# ============================================================================
# 大阪リージョン（STANDBY 側）
#
# 閉塞対象は東京。開放系・観測系は大阪を見る。
# self / peer が東京側と逆になるだけで、構造は同じ。
# 対象 Lambda の定義は functions.tf、対象リソースは locals.tf。
# ============================================================================

module "dr_switch" {
  source = "../../modules/dr-switch"

  functions = local.functions
  region    = local.self_region
  image_uri = var.image_uri

  vpc_id                                = var.vpc_id
  vpc_subnet_ids                        = var.vpc_subnet_ids
  interface_endpoint_security_group_ids = var.interface_endpoint_security_group_ids
  eks_cluster_security_group_ids         = var.eks_cluster_security_group_ids
}

# --- Kubernetes RBAC（クラスタごとに 1 回） ---------------------------------
# Kubernetes provider はクラスタごとに 1 インスタンス必要で、module 内では
# for_each で切り替えられないため、ここで個別に呼び出す。

module "rbac_cluster_a" {
  source    = "../../modules/dr-switch-rbac"
  providers = { kubernetes = kubernetes.cluster_a }

  namespaces = [for n in local.clusters["osaka-cluster-a"] : n.name]
  rbac_group = module.dr_switch.rbac_group
}

module "rbac_cluster_b" {
  source    = "../../modules/dr-switch-rbac"
  providers = { kubernetes = kubernetes.cluster_b }

  namespaces = [for n in local.clusters["osaka-cluster-b"] : n.name]
  rbac_group = module.dr_switch.rbac_group
}

output "function_arns" {
  value = module.dr_switch.function_arns
}
