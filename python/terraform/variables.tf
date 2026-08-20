# ============================================================================
# DR 切替 Lambda の IAM 定義（サンプル）
#
# 東京・大阪の両リージョンに同じ構成をデプロイする。閉塞系（block）だけが
# 相手リージョンのリソースを操作するため、そこだけ peer_* の値を使う。
# ============================================================================

variable "self_region" {
  description = "このデプロイのリージョン（開放系・観測系の対象）"
  type        = string
}

variable "peer_region" {
  description = "閉塞対象のリージョン"
  type        = string
}

# --- API Gateway -----------------------------------------------------------

variable "self_rest_api_id" {
  type = string
}

variable "self_stage" {
  type = string
}

variable "peer_rest_api_id" {
  type = string
}

variable "peer_stage" {
  type = string
}

# --- EventBridge Scheduler -------------------------------------------------

variable "self_schedule_group" {
  description = "自チーム専用のスケジュールグループ名。default は指定しない"
  type        = string
}

variable "peer_schedule_group" {
  type = string
}

variable "self_schedule_role_arn" {
  description = "スケジュールのターゲット実行ロール。UpdateSchedule の PassRole 対象"
  type        = string
}

variable "peer_schedule_role_arn" {
  type = string
}

# --- S3 --------------------------------------------------------------------

variable "self_replication_buckets" {
  description = "S3 案 A を採る場合のみ指定する"
  type        = list(string)
  default     = []
}

variable "peer_replication_buckets" {
  type    = list(string)
  default = []
}

variable "self_replication_role_arn" {
  description = "レプリケーション用ロール。PutBucketReplication の PassRole 対象"
  type        = string
  default     = null
}

variable "peer_replication_role_arn" {
  type    = string
  default = null
}

# --- Lambda / DynamoDB / EFS / EKS -----------------------------------------

variable "self_function_names" {
  description = "状態を確認する対象の Lambda 関数名"
  type        = list(string)
}

variable "self_table_names" {
  type = list(string)
}

variable "self_file_system_ids" {
  type = list(string)
}

variable "self_cluster_names" {
  type = list(string)
}

variable "pod_restart_function_names" {
  description = "restart_pods が Invoke する既存の Pod 再起動 Lambda"
  type        = list(string)
  default     = []
}

# --- Lambda 自体の配置 -----------------------------------------------------

variable "vpc_subnet_ids" {
  description = <<-EOT
    Lambda を配置するサブネット。VPC エンドポイントと EKS API サーバへ
    到達できるプライベートサブネットを指定する。
  EOT
  type        = list(string)
}

variable "alarm_prefix" {
  description = "確認対象のアラーム名の接頭辞"
  type        = string
}
