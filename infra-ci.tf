# =============================================================================
# 土台 + CI基盤の Terraform
#   方針: Helm リリース本体は CodeBuild が所有する(競合回避のため Terraform は
#         helm_release を持たない)。Terraform は helm が触らない AWS リソースのみ管理。
#
#   Terraform が所有: IAM ロール / Pod Identity / S3(filter values) /
#                     CodeBuild プロジェクト / EKS アクセスエントリ
#   CodeBuild が所有: Helm リリース(amazon-cloudwatch)。初回 install も更新も担当。
#
#   根拠リンク:
#     - aws_eks_pod_identity_association:
#       https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_pod_identity_association
#     - aws_eks_access_entry / access_policy_association:
#       https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_access_entry
#     - aws_codebuild_project:
#       https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/codebuild_project
# =============================================================================

variable "cluster_name" {
  type    = string
  default = "dev-gems-ip-eks-hybrid-cluster-001"
}
variable "region" {
  type    = string
  default = "ap-northeast-1"
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "this" {}

# -----------------------------------------------------------------------------
# 1) CloudWatch agent / Fluent Bit 用 Pod Identity ロール
#    (cloudwatch-agent ServiceAccount に紐付け。Hybrid ノードでも利用可)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "cw_observability" {
  name = "${var.cluster_name}-cw-observability"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cw_agent_server_policy" {
  role       = aws_iam_role.cw_observability.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_eks_pod_identity_association" "cw_agent" {
  cluster_name    = var.cluster_name
  namespace       = "amazon-cloudwatch"
  service_account = "cloudwatch-agent"
  role_arn        = aws_iam_role.cw_observability.arn
}

# -----------------------------------------------------------------------------
# 2) フィルタ values を置く S3 バケット
#    filter-values.yaml(= application-log.conf 全文 + grep)をここで管理する。
#    aws_s3_object.body を使わないので Content-Type 制約は不要(CodeBuild が s3 cp で取得)。
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "values" {
  bucket = "${var.cluster_name}-cw-fluentbit-values"
}

resource "aws_s3_bucket_versioning" "values" {
  bucket = aws_s3_bucket.values.id
  versioning_configuration {
    status = "Enabled" # フィルタの履歴・ロールバック用
  }
}

resource "aws_s3_bucket_public_access_block" "values" {
  bucket                  = aws_s3_bucket.values.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# 3) CodeBuild サービスロール
# -----------------------------------------------------------------------------
resource "aws_iam_role" "codebuild" {
  name = "${var.cluster_name}-cw-helm-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "codebuild" {
  name = "cw-helm-deploy"
  role = aws_iam_role.codebuild.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      },
      {
        Sid      = "ReadFilterValues"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:ListBucket"]
        Resource = [aws_s3_bucket.values.arn, "${aws_s3_bucket.values.arn}/*"]
      },
      {
        Sid      = "DescribeCluster"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = "arn:aws:eks:${var.region}:${data.aws_caller_identity.this.account_id}:cluster/${var.cluster_name}"
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# 4) CodeBuild ロールに EKS アクセス権を付与(access entry)
#    helm/kubectl で CRD・ClusterRole 等の cluster-scoped リソースも作るため、
#    初回 install を含めるなら ClusterAdmin 相当が必要。権限を絞る場合は別途検討。
# -----------------------------------------------------------------------------
resource "aws_eks_access_entry" "codebuild" {
  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.codebuild.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "codebuild" {
  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.codebuild.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope {
    type = "cluster"
  }
  depends_on = [aws_eks_access_entry.codebuild]
}

# -----------------------------------------------------------------------------
# 5) CodeBuild プロジェクト
#    source はリポジトリ(GitHub/CodeCommit 等)を想定。buildspec.yml と
#    base-values.yaml をリポジトリで管理し、filter-values.yaml のみ S3 から取得する。
# -----------------------------------------------------------------------------
resource "aws_codebuild_project" "helm_deploy" {
  name         = "${var.cluster_name}-cw-helm-deploy"
  service_role = aws_iam_role.codebuild.arn

  artifacts { type = "NO_ARTIFACTS" }

  environment {
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux2-x86_64-standard:5.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = false

    environment_variable {
      name  = "CLUSTER_NAME"
      value = var.cluster_name
    }
    environment_variable {
      name  = "AWS_REGION"
      value = var.region
    }
    environment_variable {
      name  = "VALUES_BUCKET"
      value = aws_s3_bucket.values.bucket
    }
    environment_variable {
      name  = "FILTER_VALUES_KEY"
      value = "filter-values.yaml"
    }
  }

  source {
    type = "GITHUB" # 環境に合わせて変更(CODECOMMIT/GITHUB/S3 等)
    # location  = "https://github.com/<org>/<repo>.git"
    buildspec = "buildspec.yml"
  }
}
