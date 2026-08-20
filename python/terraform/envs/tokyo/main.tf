# ============================================================================
# 東京リージョン（ACTIVE 側）
#
# 閉塞対象は大阪。開放系・観測系は東京を見る。
# 対象 Lambda の定義は functions.tf、対象リソースは locals.tf。
# ============================================================================

module "dr_switch" {
  source = "../../modules/dr-switch"

  functions = local.functions
  region    = local.self_region
  image_uri = var.image_uri

  vpc_id                                = aws_vpc.this.id
  vpc_subnet_ids                        = [for s in aws_subnet.private : s.id]
  interface_endpoint_security_group_ids = local.interface_endpoint_security_group_ids
  eks_cluster_security_group_ids        = local.eks_cluster_security_group_ids
}

# --- Kubernetes RBAC（クラスタごとに 1 回） ---------------------------------
# Kubernetes provider はクラスタごとに 1 インスタンス必要で、module 内では
# for_each で切り替えられないため、ここで個別に呼び出す。

module "rbac_cluster_a" {
  source    = "../../modules/dr-switch-rbac"
  providers = { kubernetes = kubernetes.cluster_a }

  namespaces = [for n in local.clusters[aws_eks_cluster.this["a"].name] : n.name]
  rbac_group = module.dr_switch.rbac_group
}

module "rbac_cluster_b" {
  source    = "../../modules/dr-switch-rbac"
  providers = { kubernetes = kubernetes.cluster_b }

  namespaces = [for n in local.clusters[aws_eks_cluster.this["b"].name] : n.name]
  rbac_group = module.dr_switch.rbac_group
}

output "function_arns" {
  value = module.dr_switch.function_arns
}
