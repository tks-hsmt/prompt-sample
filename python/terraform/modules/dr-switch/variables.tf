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

      handler            image_config.command に渡すハンドラ
      env                環境変数。REGION は必須
      policy             IAM ポリシーのステートメント配列
                           actions            必須
                           resources          必須
                           pass_role_service  任意。iam:PassRole の渡し先を限定する
      endpoints          この関数が到達するインターフェースエンドポイントの
                         サービス名。logs は全関数に自動で付くので書かない
      gateway_endpoints  Gateway 型（s3 / dynamodb）のサービス名
      eks_access         到達する EKS クラスタと付与するアクセスポリシー
                           cluster     クラスタ名
                           policy      AmazonEKSViewPolicy / AmazonEKSEditPolicy
                           namespaces  スコープする namespace
      timeout            任意。既定 60 秒
      vpc                任意。既定 true（全関数を VPC 内に配置する方針）
  EOT
  type = map(object({
    handler = string
    env     = map(string)
    policy = list(object({
      actions           = list(string)
      resources         = list(string)
      pass_role_service = optional(string)
    }))
    endpoints         = optional(list(string), [])
    gateway_endpoints = optional(list(string), [])
    eks_access = optional(list(object({
      cluster    = string
      policy     = string
      namespaces = list(string)
    })), [])
    timeout           = optional(number, 60)
    vpc               = optional(bool, true)
  }))
}

variable "name_prefix" {
  description = "ロール名・関数名・SG 名の接頭辞"
  type        = string
  default     = "dr-"
}

variable "image_uri" {
  description = "ECR のイメージ URI（ダイジェスト指定を推奨）"
  type        = string
}

variable "region" {
  description = "デプロイ先リージョン。プレフィックスリストの解決に使う"
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
    サービス名 -> インターフェースエンドポイントの SG ID のリスト。
    エンドポイントごとに SG が分かれている前提で、関数ごとに必要な
    エンドポイントにだけ ingress を追加する。

    functions の endpoints で指定するサービス名と、logs のキーが必要。
    例: { logs = ["sg-a"], apigateway = ["sg-b"], ... }
  EOT
  type        = map(list(string))
}

variable "log_endpoint_service" {
  description = "全関数が使うログ用エンドポイントのサービス名"
  type        = string
  default     = "logs"
}

# --- EKS --------------------------------------------------------------------

variable "eks_cluster_security_group_ids" {
  description = <<-EOT
    クラスタ名 -> EKS のマネージド SG ID。
    functions の eks_clusters で指定したクラスタのキーが必要。
  EOT
  type        = map(string)
  default     = {}
}

