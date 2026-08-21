# ============================================================================
# 別 state を引くためのバックエンド情報と、依存先の構築状況フラグ
#
# 同一 state のリソースは locals.tf でリソース参照から取る。
# 別 state は「構築済みかどうか」をフラグで制御し、未構築なら data ブロック
# ごと作らない。try() では防げない（state ファイルが読めない時点で失敗する）。
# ============================================================================

variable "image_uri" {
  description = "ECR のイメージ URI（ダイジェスト指定を推奨）"
  type        = string
}

# --- 段階 2: 別 state の EKS クラスタ ---------------------------------------

variable "external_eks_ready" {
  description = <<-EOT
    別 state の EKS クラスタを参照できるか。
    false なら、そのクラスタは確認・再起動の対象から外れる。
    同一 state のクラスタだけで eks-check / rollout-restart は動く。
  EOT
  type        = bool
  default     = false
}

variable "eks_external_state_bucket" {
  type    = string
  default = null
}

variable "eks_external_state_key" {
  type    = string
  default = null
}

# --- 段階 3: 別リージョン ---------------------------------------------------

variable "peer_ready" {
  description = <<-EOT
    相手リージョンが構築済みか。false なら閉塞系 3 関数を作らない。

    東京と大阪が互いの state を参照するため、初回は両方 false で構築し、
    双方が揃ってから true にして再適用する。
  EOT
  type        = bool
  default     = false
}

variable "peer_state_bucket" {
  type    = string
  default = null
}

variable "peer_state_key" {
  type    = string
  default = null
}
