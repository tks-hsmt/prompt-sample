# ============================================================================
# Kubernetes RBAC（1 クラスタ分）
#
# Kubernetes provider はクラスタごとに 1 インスタンス必要なため、この module を
# クラスタの数だけ呼び出し、providers で対応する provider を渡す。
#
#   module "rbac_cluster_a" {
#     source     = "../../modules/dr-switch-rbac"
#     providers  = { kubernetes = kubernetes.cluster_a }
#     namespaces = ["ns-1", "ns-2"]
#     rbac_group = "dr-switch"
#   }
#
# check は list のみ、rollout_restart は patch を別 Role で付与する。
# Node（クラスタスコープ）を確認しない設計なので ClusterRoleBinding は不要。
# ============================================================================

terraform {
  required_providers {
    kubernetes = {
      source = "hashicorp/kubernetes"
    }
  }
}

resource "kubernetes_role" "reader" {
  for_each = toset(var.namespaces)

  metadata {
    name      = "dr-switch-reader"
    namespace = each.key
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

resource "kubernetes_role" "restarter" {
  for_each = toset(var.namespaces)

  metadata {
    name      = "dr-switch-restarter"
    namespace = each.key
  }

  rule {
    api_groups = ["apps"]
    resources  = ["deployments", "daemonsets"]
    verbs      = ["patch"]
  }
}

resource "kubernetes_role_binding" "reader" {
  for_each = toset(var.namespaces)

  metadata {
    name      = "dr-switch-reader"
    namespace = each.key
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.reader[each.key].metadata[0].name
  }
  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = var.rbac_group
  }
}

resource "kubernetes_role_binding" "restarter" {
  for_each = toset(var.namespaces)

  metadata {
    name      = "dr-switch-restarter"
    namespace = each.key
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.restarter[each.key].metadata[0].name
  }
  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = var.rbac_group
  }
}
