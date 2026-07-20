# deploy/terraform/foundation/boundary.tf
# The permissions boundary that caps EVERY role the deployer creates (issue
# #109, ADR-0012). A boundary is a CEILING: a boundary-capped role's effective
# permissions are the intersection of its own policies and this document — so a
# role the deployer creates and then attaches AdministratorAccess to is still
# confined to what this allows. That is what closes Path B (see the Deny block
# in iam-deployer.tf, which forces this boundary onto every created role).
#
# Created by the foundation stack with operator creds. The deployer never
# mutates it — BoundaryPolicyImmutable in iam-deployer.tf denies that, closing
# the hole opened by naming the policy inside the annotated-maps-* prefix.
#
# Allow-set = a "service-level mirror" of the deployer's own InfraServices,
# plus exactly the out-of-family actions the vendored ALB-controller policy
# needs. Rationale and the enumerated deltas are in ADR-0012.

data "aws_iam_policy_document" "deployer_boundary" {
  # Mirror of the deployer's own non-IAM service surface (iam-deployer.tf
  # InfraServices). A capped role can never exceed the services the deployer
  # already holds, so laundering into a created role buys nothing; drawing the
  # ceiling at the service level (ec2:*, not a hand-picked action list) keeps
  # the cluster working across EKS-module and node-AMI version bumps.
  statement {
    sid    = "InfraServices"
    effect = "Allow"
    actions = [
      "ec2:*",
      "eks:*",
      "ecr:*",
      "elasticloadbalancing:*",
      "logs:*",
      "autoscaling:*",
      "kms:DescribeKey",
      "kms:ListAliases",
    ]
    resources = ["*"]
  }

  # The out-of-family actions the aws-load-balancer-controller needs at
  # runtime, derived MECHANICALLY from the vendored policy
  # (deploy/terraform/demo/policies/alb-controller-iam-policy.json, v2.17.1):
  # every action whose service prefix is NOT one of the six families above,
  # minus CreateServiceLinkedRole (handled below with its condition). This set
  # includes waf-regional:* and iam:Get/ListServerCertificate, so the boundary
  # allows two IAM READ actions beyond CreateServiceLinkedRole — see ADR-0012.
  # If the controller is ever re-vendored, re-run the derivation in Task 1
  # Step 1 of the #109 plan and update this list.
  statement {
    sid    = "AlbControllerExtras"
    effect = "Allow"
    actions = [
      "acm:DescribeCertificate",
      "acm:ListCertificates",
      "cognito-idp:DescribeUserPoolClient",
      "iam:GetServerCertificate",
      "iam:ListServerCertificates",
      "shield:CreateProtection",
      "shield:DeleteProtection",
      "shield:DescribeProtection",
      "shield:GetSubscriptionState",
      "waf-regional:AssociateWebACL",
      "waf-regional:DisassociateWebACL",
      "waf-regional:GetWebACL",
      "waf-regional:GetWebACLForResource",
      "wafv2:AssociateWebACL",
      "wafv2:DisassociateWebACL",
      "wafv2:GetWebACL",
      "wafv2:GetWebACLForResource",
    ]
    resources = ["*"]
  }

  # The one service-linked role the ALB controller creates at runtime, carrying
  # the vendored policy's own condition so the boundary doesn't widen it.
  statement {
    sid       = "AlbControllerSlr"
    effect    = "Allow"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "iam:AWSServiceName"
      values   = ["elasticloadbalancing.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "deployer_boundary" {
  name        = "annotated-maps-boundary"
  description = "Permissions boundary capping every role the deployer creates (issue #109, ADR-0012)."
  policy      = data.aws_iam_policy_document.deployer_boundary.json
}
