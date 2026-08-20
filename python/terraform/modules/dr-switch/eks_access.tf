# ============================================================================
# EKS アクセスエントリ
#
# eks = true の関数のロールを Kubernetes のグループにマッピングする。
# マネージドのアクセスポリシー（AmazonEKSViewPolicy）は使わない。
#   - cluster スコープ … 全 namespace の全リソースが読めてしまい広すぎる
#   - namespace スコープ … 必要な権限を過不足なく表現できない
#
# グループに紐づく Role / RoleBinding は modules/dr-switch-rbac で作る。
# Kubernetes provider はクラスタごとに 1 インスタンス必要で、module 内では
# for_each で切り替えられないため分離している。
# ============================================================================

resource "aws_eks_access_entry" "dr" {
  for_each = {
    for pair in setproduct(
      keys(var.eks_cluster_security_group_ids),
      [for k, v in var.functions : k if v.eks]
    ) : "${pair[0]}/${pair[1]}" => { cluster = pair[0], fn = pair[1] }
  }

  cluster_name      = each.value.cluster
  principal_arn     = aws_iam_role.dr[each.value.fn].arn
  kubernetes_groups = [var.rbac_group]
  type              = "STANDARD"
}
