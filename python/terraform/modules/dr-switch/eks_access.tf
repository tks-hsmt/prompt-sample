# ============================================================================
# EKS アクセスエントリ
#
# IAM ロールを Kubernetes のグループにマッピングする。マネージドのアクセス
# ポリシー（AmazonEKSViewPolicy）は使わない。
#   - cluster スコープ … 全 namespace の全リソースが読めてしまい広すぎる
#   - namespace スコープ … 必要な権限を過不足なく表現できない
#
# グループに紐づく Role / RoleBinding は modules/dr-switch-rbac で作る。
# Kubernetes provider はクラスタごとに 1 インスタンス必要で、module 内では
# for_each で切り替えられないため分離している。
# ============================================================================

resource "aws_eks_access_entry" "dr" {
  for_each = {
    for pair in setproduct([for c in var.eks_clusters : c.name], local.eks_functions) :
    "${pair[0]}/${pair[1]}" => { cluster = pair[0], fn = pair[1] }
  }

  cluster_name      = each.value.cluster
  principal_arn     = aws_iam_role.dr[each.value.fn].arn
  kubernetes_groups = [var.rbac_group]
  type              = "STANDARD"
}
