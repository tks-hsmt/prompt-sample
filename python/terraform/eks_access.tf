# ============================================================================
# EKS アクセスエントリと Kubernetes RBAC
#
# ワークロードの参照・更新権限は IAM ではなく Kubernetes 側で付与する。
# マネージドのアクセスポリシー（AmazonEKSViewPolicy）は使わない。
#   - cluster スコープ … 全 namespace の全リソースが読めてしまい広すぎる
#   - namespace スコープ … 必要な権限を過不足なく表現できない
# kubernetesGroups でグループにマッピングし、自前の Role を紐づける。
# ============================================================================

locals {
  dr_group = "dr-switch"

  # クラスタ名 -> 対象 namespace のリスト
  cluster_namespaces = {
    for c in var.eks_clusters : c.name => c.namespaces
  }
}

variable "eks_clusters" {
  description = "確認・再起動の対象。dr_switch の EKS_CLUSTERS と同じ内容を渡す"
  type = list(object({
    name       = string
    namespaces = list(string)
  }))
  default = []
}

# --- アクセスエントリ -------------------------------------------------------
# check と rollout_restart の 2 つのロールを同じグループにマッピングする。

resource "aws_eks_access_entry" "dr" {
  for_each = {
    for pair in setproduct(keys(local.cluster_namespaces),
    ["eks-check", "eks-rollout-restart"]) :
    "${pair[0]}/${pair[1]}" => { cluster = pair[0], fn = pair[1] }
  }

  cluster_name      = each.value.cluster
  principal_arn     = aws_iam_role.dr[each.value.fn].arn
  kubernetes_groups = [local.dr_group]
  type              = "STANDARD"
}

# --- 参照用の Role（check 用） ---------------------------------------------

resource "kubernetes_role" "dr_reader" {
  for_each = {
    for pair in flatten([
      for cluster, namespaces in local.cluster_namespaces : [
        for ns in namespaces : { cluster = cluster, namespace = ns }
      ]
    ]) : "${pair.cluster}/${pair.namespace}" => pair
  }

  metadata {
    name      = "dr-switch-reader"
    namespace = each.value.namespace
  }

  rule {
    api_groups = ["apps"]
    resources  = ["deployments", "daemonsets"]
    verbs      = ["list"]
  }
  rule {
    api_groups = [""]
    resources  = ["pods"]
    verbs      = ["list"]
  }
}

# --- 更新用の Role（rollout_restart 用） -----------------------------------
# patch は rollout_restart だけが必要。check には与えない。

resource "kubernetes_role" "dr_restarter" {
  for_each = kubernetes_role.dr_reader

  metadata {
    name      = "dr-switch-restarter"
    namespace = each.value.metadata[0].namespace
  }

  rule {
    api_groups = ["apps"]
    resources  = ["deployments", "daemonsets"]
    verbs      = ["patch"]
  }
}

resource "kubernetes_role_binding" "dr_reader" {
  for_each = kubernetes_role.dr_reader

  metadata {
    name      = "dr-switch-reader"
    namespace = each.value.metadata[0].namespace
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = each.value.metadata[0].name
  }
  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = local.dr_group
  }
}

resource "kubernetes_role_binding" "dr_restarter" {
  for_each = kubernetes_role.dr_restarter

  metadata {
    name      = "dr-switch-restarter"
    namespace = each.value.metadata[0].namespace
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = each.value.metadata[0].name
  }
  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = local.dr_group
  }
}

# ClusterRoleBinding は不要。Node（クラスタスコープ）を確認しない設計のため。
