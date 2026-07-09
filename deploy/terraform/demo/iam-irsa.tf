# deploy/terraform/demo/iam-irsa.tf
# IRSA for the aws-load-balancer-controller — the ONLY pod in the cluster
# with AWS permissions, because it's the only one that needs them (the app
# talks to Neon over TLS; ADR-0009 records this). The trust policy binds the
# role to exactly one ServiceAccount in exactly one cluster.

data "aws_iam_policy_document" "alb_controller_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
  }
}

resource "aws_iam_role" "alb_controller" {
  name               = "annotated-maps-alb-controller"
  assume_role_policy = data.aws_iam_policy_document.alb_controller_trust.json
}

resource "aws_iam_role_policy" "alb_controller" {
  name = "alb-controller"
  role = aws_iam_role.alb_controller.id
  # Vendored from the controller release (see the file header for version/URL)
  # rather than fetched at apply time: pinned, reviewable, diffable.
  # Vendored: v2.17.1
  policy = file("${path.module}/policies/alb-controller-iam-policy.json")
}
