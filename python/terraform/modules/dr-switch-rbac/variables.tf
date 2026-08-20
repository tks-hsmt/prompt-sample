variable "namespaces" {
  description = "確認・再起動の対象 namespace 名"
  type        = list(string)
}

variable "rbac_group" {
  description = "アクセスエントリの kubernetesGroups と揃える"
  type        = string
}
