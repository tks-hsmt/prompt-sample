# ============================================================================
# ネットワーク
#
# 関数ごとにセキュリティグループを作り、その関数が到達する先だけに
# egress を開く。エンドポイント側の SG にも、その関数の SG からだけ
# ingress を追加する。
#
# 全 Lambda を VPC 内に配置する。NAT ゲートウェイが無いためパブリック
# インターネットへは出られず、AWS API へは VPC エンドポイント経由で到達する。
#
# logs は全関数に必要。見落とすとログが一切出ず、しかも関数自体は
# タイムアウトするまで気づけない。
# ============================================================================

locals {
  vpc_functions = { for k, v in var.functions : k => v if v.vpc }

  # 関数 -> 到達するインターフェースエンドポイント。logs は全関数に付与する。
  function_endpoints = {
    for k, v in local.vpc_functions :
    k => distinct(concat([var.log_endpoint_service], v.endpoints))
  }

  # (関数, エンドポイント, SG) の組。エンドポイントに SG が複数付いていても
  # すべてに対してルールを作る。
  endpoint_rules = merge([
    for fn, services in local.function_endpoints : merge([
      for svc in services : {
        for sg in var.interface_endpoint_security_group_ids[svc] :
        "${fn}/${svc}/${sg}" => { fn = fn, service = svc, sg = sg }
      }
    ]...)
  ]...)

  gateway_rules = merge([
    for fn, v in local.vpc_functions : {
      for svc in v.gateway_endpoints : "${fn}/${svc}" => { fn = fn, service = svc }
    }
  ]...)

  # 関数 -> 到達する EKS クラスタ。SG ルールとアクセスエントリのキーになる。
  eks_rules = merge([
    for fn, v in local.vpc_functions : {
      for a in v.eks_access : "${fn}/${a.cluster}" => {
        fn         = fn
        cluster    = a.cluster
        policy     = a.policy
        namespaces = a.namespaces
      }
    }
  ]...)

  gateway_services = distinct(flatten([
    for v in local.vpc_functions : v.gateway_endpoints
  ]))

  # 相手リージョンのエンドポイントを使う関数。
  # リージョン間 VPC ピアリングでは相手 SG を参照できないため CIDR で書く。
  peer_endpoint_functions = {
    for k, v in local.vpc_functions : k => v if length(v.peer_endpoints) > 0
  }
}

# --- 関数ごとのセキュリティグループ -----------------------------------------

resource "aws_security_group" "dr_lambda" {
  for_each = local.vpc_functions

  name        = "${var.name_prefix}${each.key}"
  description = "DR switch Lambda: ${each.key}"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name_prefix}${each.key}"
  }
}

# --- インターフェースエンドポイントへの経路 ---------------------------------

resource "aws_security_group_rule" "egress_endpoint" {
  for_each = local.endpoint_rules

  type                     = "egress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.dr_lambda[each.value.fn].id
  source_security_group_id = each.value.sg
  description              = "to ${each.value.service} endpoint"
}

resource "aws_security_group_rule" "endpoint_from_dr_lambda" {
  for_each = local.endpoint_rules

  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = each.value.sg
  source_security_group_id = aws_security_group.dr_lambda[each.value.fn].id
  description              = "from ${var.name_prefix}${each.value.fn}"
}

# --- Gateway 型エンドポイントへの経路 ---------------------------------------
# Gateway 型（s3 / dynamodb）はセキュリティグループを持たない。ルート
# テーブルに関連付けられていれば到達でき、Lambda 側はプレフィックスリスト宛の
# アウトバウンドを許可する。
#
# プレフィックスリストは AWS が管理していて常に存在するため data で引いてよい。
# 自チームが作成するリソースではないので、初回 apply でも失敗しない。

data "aws_ec2_managed_prefix_list" "gateway" {
  for_each = toset(local.gateway_services)
  name     = "com.amazonaws.${var.region}.${each.key}"
}

resource "aws_security_group_rule" "egress_gateway" {
  for_each = local.gateway_rules

  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.dr_lambda[each.value.fn].id
  prefix_list_ids   = [data.aws_ec2_managed_prefix_list.gateway[each.value.service].id]
  description       = "to ${each.value.service} gateway endpoint"
}

# --- 相手リージョンのエンドポイントへの経路 ---------------------------------
# 閉塞系（block）は相手リージョンの API を叩く。クロスリージョン PrivateLink は
# apigateway / scheduler に未対応のため、相手リージョン側の Interface VPCE へ
# VPC Peering と Route 53 Resolver の条件付き転送で到達する。
#
# **リージョン間 VPC ピアリングでは相手リージョンの SG を参照できない**
# （公式に「別リージョンのピア VPC のセキュリティグループは参照できない。
# 代わりにピア VPC の CIDR ブロックを使う」と明記）。そのため CIDR で書く。
#
# Gateway 型は同一リージョンにしかルーティングしないので、相手リージョンの
# S3 へは Interface エンドポイント経由になる（peer_endpoints に "s3" を指定）。
#
# 相手側エンドポイントの SG に対する ingress（自 VPC の CIDR からの 443）は
# 相手リージョンの state が管理する。ここでは作れない。

resource "aws_security_group_rule" "egress_peer_endpoint" {
  for_each = local.peer_endpoint_functions

  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.dr_lambda[each.key].id
  cidr_blocks       = var.peer_endpoint_cidr_blocks
  description       = "to peer region endpoints (${join(",", each.value.peer_endpoints)})"
}

# --- EKS クラスタへの経路 ---------------------------------------------------
# クラスタのマネージド SG（EKS が作成し、コントロールプレーンの ENI に付く）
# へ Lambda の SG からの 443 を許可する。これが無いと kubeconfig を作れても
# API サーバへ到達できない。

resource "aws_security_group_rule" "egress_eks" {
  for_each = local.eks_rules

  type                     = "egress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.dr_lambda[each.value.fn].id
  source_security_group_id = var.eks_cluster_security_group_ids[each.value.cluster]
  description              = "to EKS API server (${each.value.cluster})"
}

resource "aws_security_group_rule" "eks_from_dr_lambda" {
  for_each = local.eks_rules

  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = var.eks_cluster_security_group_ids[each.value.cluster]
  source_security_group_id = aws_security_group.dr_lambda[each.value.fn].id
  description              = "from ${var.name_prefix}${each.value.fn}"
}
