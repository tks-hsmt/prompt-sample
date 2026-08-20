terraform {
  required_version = ">= 1.9"

  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 5.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.0" }
  }

  # backend "s3" { ... }
}

provider "aws" {
  region = local.self_region
}

# Kubernetes provider はクラスタごとに 1 インスタンス必要。
# module 内では for_each で切り替えられないため、ここで alias を切る。
#
# ★ aws_eks_cluster.this のキー（"a" / "b"）は仮。実際の構成に合わせること。

data "aws_eks_cluster_auth" "this" {
  for_each = aws_eks_cluster.this
  name     = each.value.name
}

provider "kubernetes" {
  alias                  = "cluster_a"
  host                   = aws_eks_cluster.this["a"].endpoint
  cluster_ca_certificate = base64decode(aws_eks_cluster.this["a"].certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.this["a"].token
}

provider "kubernetes" {
  alias                  = "cluster_b"
  host                   = aws_eks_cluster.this["b"].endpoint
  cluster_ca_certificate = base64decode(aws_eks_cluster.this["b"].certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.this["b"].token
}
