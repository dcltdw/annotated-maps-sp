# deploy/terraform/demo/network.tf
# Community module for commodity plumbing (ADR-0009 / spec fork 1): the
# subnet arithmetic isn't the exhibit — the IAM files are.
data "aws_availability_zones" "available" {
  state = "available"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "annotated-maps-demo"
  cidr = "10.0.0.0/16"

  azs             = slice(data.aws_availability_zones.available.names, 0, 2)
  public_subnets  = ["10.0.0.0/20", "10.0.16.0/20"]
  private_subnets = ["10.0.128.0/20", "10.0.144.0/20"]

  # COST DECISION: one NAT gateway, not per-AZ (~$0.045/hr each). An
  # ephemeral demo does not need AZ-fault-tolerant egress.
  enable_nat_gateway = true
  single_nat_gateway = true

  # ALB controller discovers subnets by these role tags.
  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}
