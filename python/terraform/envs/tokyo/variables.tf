# ============================================================================
# 別 state から受け取る値
#
# 同一 state のリソースは locals.tf でリソース参照から取るので、ここには
# 現れない。相手リージョンのリソースと、別 state のエンドポイント SG だけ。
#
# terraform_remote_state で引く場合は、この変数を消して locals.tf 側で
# data.terraform_remote_state.xxx.outputs.yyy を参照する。
# ============================================================================

variable "image_uri" {
  description = "ECR のイメージ URI（ダイジェスト指定を推奨）"
  type        = string
}

# --- 相手リージョン（閉塞対象） ---------------------------------------------

variable "peer_rest_api_id" { type = string }
variable "peer_stage_name" { type = string }
variable "peer_schedule_group" { type = string }
variable "peer_schedule_arn" { type = string }
variable "peer_schedule_role_arn" { type = string }
variable "peer_replication_buckets" { type = list(string) }
variable "peer_replication_bucket_arns" { type = list(string) }
variable "peer_replication_role_arn" { type = string }

# --- 別 state のインターフェースエンドポイント ------------------------------

variable "interface_endpoint_security_group_ids" {
  description = <<-EOT
    サービス名 -> インターフェースエンドポイントの SG ID。
    functions の endpoints で指定するサービス名と logs のキーが必要。
  EOT
  type        = map(string)
}

# --- EKS provider 設定 ------------------------------------------------------
# aws_eks_cluster.this から取れるが、provider ブロックでは module の出力を
# 使えないため、cluster リソースの属性を直接参照する（providers.tf を参照）。
