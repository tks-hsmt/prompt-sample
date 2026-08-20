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
data "aws_eks_cluster_auth" "cluster_a" {
  name = local.cluster_a
}

provider "kubernetes" {
  alias                  = "cluster_a"
  host                   = var.cluster_a_endpoint
  cluster_ca_certificate = base64decode(var.cluster_a_ca_data)
  token                  = data.aws_eks_cluster_auth.cluster_a.token
}

data "aws_eks_cluster_auth" "cluster_b" {
  name = local.cluster_b
}

provider "kubernetes" {
  alias                  = "cluster_b"
  host                   = var.cluster_b_endpoint
  cluster_ca_certificate = base64decode(var.cluster_b_ca_data)
  token                  = data.aws_eks_cluster_auth.cluster_b.token
}
