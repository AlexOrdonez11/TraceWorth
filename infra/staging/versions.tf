terraform {
  required_version = ">= 1.10, < 2.0"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = "TraceWorth", Environment = "staging", Owner = "Alex", ManagedBy = "Terraform" }
  }
}
provider "aws" {
  alias               = "edge"
  region              = "us-east-1"
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = "TraceWorth", Environment = "staging", ManagedBy = "Terraform" }
  }
}
data "aws_availability_zones" "available" { state = "available" }
locals { name = "traceworth-staging" }
