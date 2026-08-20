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

  vpc_id                                = aws_vpc.this.id
  vpc_subnet_ids                        = [for s in aws_subnet.private : s.id]
  interface_endpoint_security_group_ids = local.interface_endpoint_security_group_ids
  eks_cluster_security_group_ids        = local.eks_cluster_security_group_ids
}

output "function_arns" {
  value = module.dr_switch.function_arns
}
