# ============================================================================
# module の入力
#
# 東京・大阪の両リージョンに同じ構成をデプロイする。閉塞系（block）だけが
# 相手リージョンのリソースを操作するため、そこだけ peer_* の値を使う。
#
# 対象リソースの ID は呼び出し側から注入する。同一 state でリソースを管理して
# いるなら、リソース参照をそのまま渡すこと
# （例: self_rest_api_id = aws_api_gateway_rest_api.this.id）。
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

variable "throttle_rate" {
  description = "開放時に戻すスロットリング値。現在ステージに設定されている値と揃える"
  type        = string
  default     = "10000"
}

variable "throttle_burst" {
  type    = string
  default = "5000"
}

variable "image_uri" {
  description = "ECR のイメージ URI（ダイジェスト指定を推奨）"
  type        = string
}

variable "self_target_group_arns" {
  type = list(string)
}

variable "self_load_balancer_arns" {
  type    = list(string)
  default = []
}

variable "pod_restart_timeout" {
  description = "呼ばれる側の Lambda の Timeout に合わせる"
  type        = number
  default     = 300
}

variable "eks_clusters" {
  description = <<-EOT
    確認・再起動の対象。dr_switch の EKS_CLUSTERS にそのまま渡す内容。
    restart_targets が空の namespace は check の対象にはなるが再起動しない。
  EOT
  type = list(object({
    name = string
    namespaces = list(object({
      name = string
      restart_targets = optional(list(object({
        kind = string
        name = string
      })), [])
    }))
  }))
  default = []
}

variable "alarm_prefix" {
  description = "確認対象のアラーム名の接頭辞"
  type        = string
}

variable "vpc_id" {
  type = string
}
variable "eks_cluster_security_group_ids" {
  description = <<-EOT
    クラスタ名 -> EKS のマネージド SG ID。
    同一 state でクラスタを管理しているなら
    { for k, c in aws_eks_cluster.this : k => c.vpc_config[0].cluster_security_group_id }
    のように直接渡す。別 state なら remote state か tfvars から渡す。
  EOT
  type        = map(string)
}
variable "interface_endpoint_security_group_ids" {
  description = <<-EOT
    既存のインターフェースエンドポイントに付いているセキュリティグループ ID。
    ここへ Lambda の SG からのインバウンド 443 を追加する。
    複数のエンドポイントが同じ SG を共有している場合は重複を除いて渡すこと。
  EOT
  type        = list(string)
}

variable "rbac_group" {
  description = "EKS アクセスエントリの kubernetesGroups。RBAC module と揃える"
  type        = string
  default     = "dr-switch"
}
