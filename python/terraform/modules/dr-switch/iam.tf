# ============================================================================
# 実行ロールとポリシー
#
# ここは local.functions を for_each で回すだけ。関数が増えても
# functions.tf にエントリを足すだけでよく、このファイルは変更不要。
# ============================================================================

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "dr" {
  for_each = local.functions

  dynamic "statement" {
    for_each = each.value.policy
    content {
      effect    = "Allow"
      actions   = statement.value.actions
      resources = statement.value.resources

      # iam:PassRole の渡し先を限定する。pass_role_service を
      # 指定したステートメントにだけ付く。
      dynamic "condition" {
        for_each = lookup(statement.value, "pass_role_service", null) == null ? [] : [1]
        content {
          test     = "StringEquals"
          variable = "iam:PassedToService"
          values   = [statement.value.pass_role_service]
        }
      }
    }
  }
}

resource "aws_iam_role" "dr" {
  for_each           = local.functions
  name               = "dr-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "dr" {
  for_each = local.functions
  name     = "dr-${each.key}"
  role     = aws_iam_role.dr[each.key].id
  policy   = data.aws_iam_policy_document.dr[each.key].json
}

# CloudWatch Logs への書き込み。全関数に必要。
resource "aws_iam_role_policy_attachment" "basic" {
  for_each   = local.functions
  role       = aws_iam_role.dr[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC 配置する関数には ENI の作成・削除権限が要る。
resource "aws_iam_role_policy_attachment" "vpc" {
  for_each   = { for k, v in local.functions : k => v if lookup(v, "vpc", true) }
  role       = aws_iam_role.dr[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
