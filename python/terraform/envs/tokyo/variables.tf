# ============================================================================
# 別 state を引くためのバックエンド情報
#
# 同一 state のリソースは locals.tf でリソース参照から取る。
# 別 state のうち output があるものは terraform_remote_state、無いものは
# data ソースで引く。どちらも locals.tf に書いてあるので、ここには
# バックエンドの場所だけが残る。
# ============================================================================

variable "image_uri" {
  description = "ECR のイメージ URI（ダイジェスト指定を推奨）"
  type        = string
}

# --- 相手リージョンの state（閉塞対象） -------------------------------------
# 必要な output: rest_api_id / stage_name / schedule_group / schedule_role_arn
#                replication_buckets / replication_bucket_arns / replication_role_arn

variable "peer_state_bucket" { type = string }
variable "peer_state_key" { type = string }

# --- 別 state の EKS クラスタ -----------------------------------------------
# 必要な output: cluster_name / cluster_arn / cluster_security_group_id

variable "eks_external_state_bucket" { type = string }
variable "eks_external_state_key" { type = string }
