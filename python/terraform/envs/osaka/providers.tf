terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }

  # backend "s3" { ... }
}

provider "aws" {
  region = local.self_region
}

# Kubernetes provider は不要。ワークロードの権限は EKS のアクセスポリシーを
# namespace スコープで付与するため、Terraform の適用にクラスタへの到達性も
# 要らない。
