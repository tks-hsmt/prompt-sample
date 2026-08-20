# ============================================================================
# DR 切替 Lambda のネットワーク設定
#
# 全 Lambda を VPC 内に配置する。NAT ゲートウェイが無いためパブリック
# インターネットへは出られず、AWS API へは VPC エンドポイント経由で到達する。
#
# 必要な経路（実装から洗い出したもの）
#
#   接続先                          用途                    エンドポイント種別
#   ------------------------------  ----------------------  ------------------
#   logs                            全関数のログ出力        Interface
#   apigateway                      apigateway 系 3 関数    Interface
#   scheduler                       scheduler 系 3 関数     Interface
#   elasticloadbalancing            nlb-check               Interface
#   monitoring                      cloudwatch-check        Interface
#   lambda                          lambda-check /          Interface
#                                   eks-restart-pods
#   elasticfilesystem               efs-check               Interface
#   eks                             eks 系 2 関数           Interface
#   eks-auth                        eks 系 2 関数（トークン取得）Interface
#   sts                             eks 系 2 関数           Interface
#   s3                              s3 系 3 関数            Gateway（ルートテーブル）
#   dynamodb                        dynamodb-check          Gateway（ルートテーブル）
#
# Gateway 型（s3 / dynamodb）はセキュリティグループを持たないため、
# ルートテーブルにエンドポイントが関連付けられていれば到達できる。
# ============================================================================

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

# --- Lambda 用セキュリティグループ ------------------------------------------

resource "aws_security_group" "dr_lambda" {
  name        = "dr-switch-lambda"
  description = "DR switch Lambda functions"
  vpc_id      = var.vpc_id

  tags = {
    Name = "dr-switch-lambda"
  }
}

# アウトバウンドは AWS API への HTTPS のみ。
# VPC エンドポイント経由なので宛先は VPC 内に閉じるが、エンドポイントの
# プライベート IP は変動しうるため CIDR ではなく宛先 SG で絞る。
resource "aws_security_group_rule" "dr_lambda_egress_endpoints" {
  for_each = toset(var.interface_endpoint_security_group_ids)

  type                     = "egress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.dr_lambda.id
  source_security_group_id = each.value
  description              = "to interface VPC endpoints"
}

# for_each のキーは plan 時に確定している必要があるため、data の結果ではなく
# 変数を使う。data は値（SG ID）の参照にだけ使う。
resource "aws_security_group_rule" "dr_lambda_egress_eks" {
  for_each = var.eks_cluster_security_group_ids

  type                     = "egress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.dr_lambda.id
  source_security_group_id = each.value
  description              = "to EKS API server (${each.key})"
}

# Gateway 型エンドポイント（s3 / dynamodb）はプレフィックスリスト宛の
# アウトバウンドが要る。宛先 SG では表現できない。
#
# プレフィックスリストは AWS が管理していて常に存在するため data で引いてよい。
# 自チームが作成するリソースではないので、初回 apply でも失敗しない。
data "aws_ec2_managed_prefix_list" "gateway" {
  for_each = toset(["s3", "dynamodb"])
  name     = "com.amazonaws.${var.self_region}.${each.key}"
}

resource "aws_security_group_rule" "dr_lambda_egress_gateway" {
  for_each = toset(["s3", "dynamodb"])

  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.dr_lambda.id
  prefix_list_ids   = [data.aws_ec2_managed_prefix_list.gateway[each.key].id]
  description       = "to ${each.key} gateway endpoint"
}

# --- インターフェースエンドポイント側のインバウンド --------------------------

resource "aws_security_group_rule" "endpoint_from_dr_lambda" {
  for_each = toset(var.interface_endpoint_security_group_ids)

  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = each.value
  source_security_group_id = aws_security_group.dr_lambda.id
  description              = "from DR switch Lambda"
}

# --- EKS クラスタ側のインバウンド -------------------------------------------
# クラスタのマネージド SG（EKS が作成し、コントロールプレーンの ENI に付く）
# へ Lambda の SG からの 443 を許可する。これが無いと kubeconfig を作れても
# API サーバへ到達できない。
#
# SG ID は変数で受け取る。data で引くと、クラスタを同じ Terraform で作る
# 構成では初回 apply 時にまだ存在せず失敗する。同一 state ならクラスタ
# リソースの vpc_config[0].cluster_security_group_id を直接渡すこと。

resource "aws_security_group_rule" "eks_from_dr_lambda" {
  for_each = var.eks_cluster_security_group_ids

  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = each.value
  source_security_group_id = aws_security_group.dr_lambda.id
  description              = "DR switch Lambda -> EKS API server (${each.key})"
}

output "lambda_security_group_id" {
  value = aws_security_group.dr_lambda.id
}
