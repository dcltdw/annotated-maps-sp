# deploy/terraform/demo/boundary.tf
# The deployer's permissions boundary lives in the foundation stack (applied
# with operator creds; issue #109, ADR-0012). This ephemeral stack, applied AS
# the deployer, only needs the boundary's ARN so the roles it creates carry it
# — without it the deployer's DenyRoleCreateWithoutBoundary blocks CreateRole.
#
# foundation's state is a local, operator-only file, so terraform_remote_state
# cannot reach it. The policy NAME is the cross-stack contract instead:
# foundation/boundary.tf creates "annotated-maps-boundary" and
# foundation/outputs.tf exports its ARN; here we reconstruct that ARN.
data "aws_caller_identity" "current" {}

locals {
  deployer_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/annotated-maps-boundary"
}
