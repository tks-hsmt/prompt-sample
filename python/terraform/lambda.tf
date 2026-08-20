# ============================================================================
# Lambda 関数
#
# ここも local.functions を for_each で回すだけ。全関数が同一のコンテナ
# イメージを共有し、image_config.command でハンドラを切り替える。Lambda は
# イメージをダイジェスト単位でキャッシュするため、共有すると最初の 1 本が
# キャッシュを温め残りがその恩恵を受ける。
# ============================================================================

resource "aws_lambda_function" "dr" {
  for_each = local.functions

  function_name = "dr-${each.key}"
  role          = aws_iam_role.dr[each.key].arn
  package_type  = "Image"
  image_uri     = var.image_uri
  timeout       = lookup(each.value, "timeout", local.default_timeout)

  image_config {
    command = [each.value.handler]
  }

  environment {
    variables = each.value.env
  }

  # NAT ゲートウェイが無いため、AWS API へは VPC エンドポイント経由で到達する
  # （network.tf を参照）。
  dynamic "vpc_config" {
    for_each = lookup(each.value, "vpc", true) ? [1] : []
    content {
      subnet_ids         = var.vpc_subnet_ids
      security_group_ids = [aws_security_group.dr_lambda.id]
    }
  }

  depends_on = [
    aws_iam_role_policy.dr,
    aws_iam_role_policy_attachment.basic,
    aws_iam_role_policy_attachment.vpc,
    aws_security_group_rule.endpoint_from_dr_lambda,
    aws_security_group_rule.eks_from_dr_lambda,
  ]
}

output "function_arns" {
  description = "Step Functions の ASL に埋める関数 ARN"
  value       = { for k, f in aws_lambda_function.dr : k => f.arn }
}
