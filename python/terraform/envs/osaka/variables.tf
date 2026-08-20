# ============================================================================
# 環境固有の値
#
# 同一 state で対象リソースを管理しているなら、変数ではなくリソース参照を
# module へ直接渡すこと。ここは別 state で管理している前提のサンプル。
# ============================================================================

variable "image_uri" {
  description = "ECR のイメージ URI（ダイジェスト指定を推奨）"
  type        = string
}

# --- EKS の provider 設定に使う ---------------------------------------------

variable "cluster_a_endpoint" { type = string }
variable "cluster_a_ca_data" { type = string }
variable "cluster_b_endpoint" { type = string }
variable "cluster_b_ca_data" { type = string }

# --- module へ渡す ID / ARN --------------------------------------------------

variable "self_rest_api_id" { type = string }
variable "peer_rest_api_id" { type = string }
variable "self_schedule_role_arn" { type = string }
variable "peer_schedule_role_arn" { type = string }
variable "self_replication_role_arn" { type = string }
variable "peer_replication_role_arn" { type = string }
variable "vpc_id" { type = string }
variable "vpc_subnet_ids" { type = list(string) }
variable "interface_endpoint_security_group_ids" { type = list(string) }
variable "eks_cluster_security_group_ids" { type = map(string) }
variable "self_target_group_arns" { type = list(string) }
variable "self_load_balancer_arns" { type = list(string) }
