# ============================================================================
# EKS アクセスエントリとアクセスポリシーの関連付け
#
# 前提としてクラスタの authenticationMode が API または API_AND_CONFIG_MAP で
# あること（CONFIG_MAP では作成できない。一度有効にすると元に戻せない）。
#
# 権限は AWS マネージドのアクセスポリシーを namespace スコープで付与する。
# 自前の Role / RoleBinding を作る方式もあるが、Kubernetes provider が必要に
# なり、クラスタごとに provider の alias を切ることになる。Terraform の適用に
# クラスタへの到達性も要る。
#
# rollout_restart に patch を許可するポリシーは AmazonEKSEditPolicy しかなく、
# Pod の削除やリソース作成も含まれる。自前ポリシーは作成できないため選択肢が
# 無い。ただしここで動くのは自分たちが書いたコードだけで、コードは
# patch_namespaced_deployment しか呼ばない。
# ============================================================================

resource "aws_eks_access_entry" "dr" {
  for_each = local.eks_rules

  cluster_name  = each.value.cluster
  principal_arn = aws_iam_role.dr[each.value.fn].arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "dr" {
  for_each = local.eks_rules

  cluster_name  = each.value.cluster
  principal_arn = aws_iam_role.dr[each.value.fn].arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/${each.value.policy}"

  access_scope {
    type       = "namespace"
    namespaces = each.value.namespaces
  }

  depends_on = [aws_eks_access_entry.dr]
}
