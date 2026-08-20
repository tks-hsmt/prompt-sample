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

  # (関数, エンドポイント) の組。SG ルールのキーになる。
  endpoint_rules = merge([
    for fn, services in local.function_endpoints : {
      for svc in services : "${fn}/${svc}" => { fn = fn, service = svc }
    }
  ]...)

  gateway_rules = merge([
    for fn, v in local.vpc_functions : {
      for svc in v.gateway_endpoints : "${fn}/${svc}" => { fn = fn, service = svc }
    }
  ]...)

  eks_rules = merge([
    for fn, v in local.vpc_functions : {
      for cluster in v.eks_clusters : "${fn}/${cluster}" => { fn = fn, cluster = cluster }
    }
  ]...)

  gateway_services = distinct(flatten([
    for v in local.vpc_functions : v.gateway_endpoints
  ]))
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
  source_security_group_id = var.interface_endpoint_security_group_ids[each.value.service]
  description              = "to ${each.value.service} endpoint"
}

resource "aws_security_group_rule" "endpoint_from_dr_lambda" {
  for_each = local.endpoint_rules

  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = var.interface_endpoint_security_group_ids[each.value.service]
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
