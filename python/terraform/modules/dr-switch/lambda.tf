# ============================================================================
# Lambda 関数
#
# 全関数が同一のコンテナイメージを共有し、image_config.command でハンドラを
# 切り替える。Lambda はイメージをダイジェスト単位でキャッシュするため、
# 共有すると最初の 1 本がキャッシュを温め残りがその恩恵を受ける。
# ============================================================================

resource "aws_lambda_function" "dr" {
  for_each = var.functions

  function_name = "${var.name_prefix}${each.key}"
  role          = aws_iam_role.dr[each.key].arn
  package_type  = "Image"
  image_uri     = var.image_uri
  timeout       = each.value.timeout

  image_config {
    command = [each.value.handler]
  }

  environment {
    variables = each.value.env
  }

  # NAT ゲートウェイが無いため、AWS API へは VPC エンドポイント経由で到達する
  # （network.tf を参照）。
  dynamic "vpc_config" {
    for_each = each.value.vpc ? [1] : []
    content {
      subnet_ids         = var.vpc_subnet_ids
      security_group_ids = [aws_security_group.dr_lambda[each.key].id]
    }
  }

  depends_on = [
    aws_iam_role_policy.dr,
    aws_iam_role_policy_attachment.basic,
    aws_iam_role_policy_attachment.vpc,
    aws_security_group_rule.egress_endpoint,
    aws_security_group_rule.endpoint_from_dr_lambda,
    aws_security_group_rule.egress_gateway,
    aws_security_group_rule.egress_eks,
    aws_security_group_rule.eks_from_dr_lambda,
  ]
}
