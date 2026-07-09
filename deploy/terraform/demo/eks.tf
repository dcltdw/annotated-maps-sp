# deploy/terraform/demo/eks.tf
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.31" # newest supported at pin time; bump if the module rejects it

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Ephemeral demo, no bastion/VPN: public API endpoint (spec §2 trade-off).
  cluster_endpoint_public_access = true

  # The operator identity that runs terraform apply gets cluster-admin.
  enable_cluster_creator_admin_permissions = true

  # IRSA: creates the cluster's OIDC provider; our hand-written trust
  # policies (iam-irsa.tf) consume it.
  enable_irsa = true

  cluster_addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = {}
  }

  eks_managed_node_groups = {
    default = {
      # 2x t3.medium ON_DEMAND: spot reclaims mid-debug-cycle cost more than
      # they save at this scale (spec §2).
      instance_types = ["t3.medium"]
      capacity_type  = "ON_DEMAND"
      min_size       = 2
      max_size       = 2
      desired_size   = 2
    }
  }
}
