# ============================================================================
# module の入力
#
# 対象 Lambda の定義は呼び出し側（envs/*）が持つ。この module は渡された
# 定義に従ってロール・ポリシー・関数・ネットワーク許可を作るだけで、
# 対象が増えても変数は変わらない。
# ============================================================================

variable "functions" {
  description = <<-EOT
    関数名 -> 定義。

      handler  コンテナイメージの image_config.command に渡すハンドラ
      env      環境変数。REGION は必須
      policy   IAM ポリシーのステートメント配列
                 actions            必須
                 resources          必須
                 pass_role_service  任意。iam:PassRole の渡し先を限定する
      timeout  任意。既定 60 秒
      vpc      任意。既定 true（全関数を VPC 内に配置する方針）
      eks      任意。既定 false。true なら EKS アクセスエントリを作る
  EOT
  type = map(object({
    handler = string
    env     = map(string)
    policy = list(object({
      actions           = list(string)
      resources         = list(string)
      pass_role_service = optional(string)
    }))
    timeout = optional(number, 60)
    vpc     = optional(bool, true)
    eks     = optional(bool, false)
  }))
}

variable "name_prefix" {
  description = "ロール名・関数名の接頭辞"
  type        = string
  default     = "dr-"
}

variable "image_uri" {
  description = "ECR のイメージ URI（ダイジェスト指定を推奨）"
  type        = string
}

# --- ネットワーク -----------------------------------------------------------

variable "vpc_id" {
  type = string
}

variable "vpc_subnet_ids" {
  description = <<-EOT
    Lambda を配置するサブネット。VPC エンドポイントと EKS API サーバへ
    到達できるプライベートサブネットを指定する。
  EOT
  type        = list(string)
}

variable "interface_endpoint_security_group_ids" {
  description = <<-EOT
    既存のインターフェースエンドポイントに付いているセキュリティグループ ID。
    ここへ Lambda の SG からのインバウンド 443 を追加する。
    複数のエンドポイントが同じ SG を共有している場合は重複を除いて渡すこと。
  EOT
  type        = list(string)
}

variable "gateway_endpoint_services" {
  description = "プレフィックスリスト宛の egress を許可する Gateway 型エンドポイント"
  type        = list(string)
  default     = ["s3", "dynamodb"]
}

variable "region" {
  description = "この module をデプロイするリージョン。プレフィックスリストの解決に使う"
  type        = string
}

# --- EKS --------------------------------------------------------------------

variable "eks_cluster_security_group_ids" {
  description = <<-EOT
    クラスタ名 -> EKS のマネージド SG ID。
    同一 state でクラスタを管理しているなら
    { for k, c in aws_eks_cluster.this : k => c.vpc_config[0].cluster_security_group_id }
    のように直接渡す。
  EOT
  type        = map(string)
  default     = {}
}

variable "rbac_group" {
  description = "EKS アクセスエントリの kubernetesGroups。RBAC module と揃える"
  type        = string
  default     = "dr-switch"
}
