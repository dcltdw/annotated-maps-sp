# deploy/terraform/demo/eks.tf
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name = var.cluster_name
  # Bumped 2026-07-16: AWS notified that EKS extended support for 1.31 ends
  # 2026-11-26. The clusters here are ephemeral (recreated every pipeline run,
  # never upgraded in place), so this is just "which version each fresh run
  # creates" — no live-cluster migration. Kept inside the current module major
  # (~> 20.0), which handles 1.33; going to the latest (1.35) would likely
  # need the module's next major, out of scope for a version bump. The addons
  # below are `{}`, so the module auto-resolves versions compatible with this
  # one. Final apply-time compatibility is proven by the next live run.
  cluster_version = "1.33"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Ephemeral demo, no bastion/VPN: public API endpoint (spec §2 trade-off).
  cluster_endpoint_public_access = true

  # The operator identity that runs terraform apply gets cluster-admin.
  enable_cluster_creator_admin_permissions = true

  # IRSA: creates the cluster's OIDC provider; our hand-written trust
  # policies (iam-irsa.tf) consume it.
  enable_irsa = true

  # No customer-managed KMS key for cluster-secrets envelope encryption. The
  # demo holds zero sensitive data and lives for hours; the CMK's only real
  # effect here was a ~$1/mo pending-deletion charge accruing PER RUN, since
  # terraform destroy can only SCHEDULE key deletion (7-30 day window).
  # Control-plane storage is AWS-encrypted regardless. See ADR-0010.
  create_kms_key            = false
  cluster_encryption_config = {}

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

      # The deployer role's IAM boundary is the annotated-maps-* prefix; the
      # module's default node-role name ("default-eks-node-group-...") falls
      # outside it. Name it inside.
      iam_role_name            = "annotated-maps-node"
      iam_role_use_name_prefix = true
    }
  }
}
