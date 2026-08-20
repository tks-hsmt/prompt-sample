# ============================================================================
# module の出力
# ============================================================================

output "function_arns" {
  description = "Step Functions の ASL に埋める関数 ARN"
  value       = { for k, f in aws_lambda_function.dr : k => f.arn }
}

output "role_arns" {
  description = "各関数の実行ロール"
  value       = { for k, r in aws_iam_role.dr : k => r.arn }
}

output "lambda_security_group_id" {
  description = "各種エンドポイントの許可設定に使う"
  value       = aws_security_group.dr_lambda.id
}

output "rbac_group" {
  description = "RBAC module に渡すグループ名"
  value       = var.rbac_group
}

output "cluster_namespaces" {
  description = "RBAC module に渡す namespace（クラスタ名 -> namespace 名のリスト）"
  value       = { for c in var.eks_clusters : c.name => [for n in c.namespaces : n.name] }
}
