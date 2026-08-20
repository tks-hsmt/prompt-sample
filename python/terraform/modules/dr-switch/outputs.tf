output "function_arns" {
  description = "Step Functions の ASL に埋める関数 ARN"
  value       = { for k, f in aws_lambda_function.dr : k => f.arn }
}

output "role_arns" {
  description = "各関数の実行ロール"
  value       = { for k, r in aws_iam_role.dr : k => r.arn }
}

output "security_group_ids" {
  description = "関数名 -> セキュリティグループ"
  value       = { for k, s in aws_security_group.dr_lambda : k => s.id }
}

output "rbac_group" {
  description = "RBAC module に渡すグループ名"
  value       = var.rbac_group
}
