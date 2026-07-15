# deploy/terraform/foundation/iam-deployer.tf
# The pipeline's apply-capable role (ADR-0010). Contrast with annotated-maps-ci
# (iam-ci.tf), which is read-only plan: this role CAN create and destroy the
# demo stack. Honest scoping: terraform apply of VPC+EKS+ECR legitimately
# needs broad service powers, so those are granted per-service — and the
# boundary is enforced where it matters: IAM is restricted to the
# annotated-maps-* prefix, S3 to the state bucket, SNS to the alerts topic.
#
# Trust: exactly one OIDC subject — the unprotected `aws-deploy` GitHub
# Environment. workflow_dispatch/schedule can't be triggered by forks and
# dispatching requires write access; there is deliberately NO required
# reviewer (dispatch IS the confirmation, and a reviewer-gated destroy job
# could hang teardown — see ADR-0010).

data "aws_iam_policy_document" "deployer_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:dcltdw/annotated-maps-sp:environment:aws-deploy"]
    }
  }
}

resource "aws_iam_role" "deployer" {
  name               = "annotated-maps-deployer"
  assume_role_policy = data.aws_iam_policy_document.deployer_trust.json
}

data "aws_iam_policy_document" "deployer_permissions" {
  # Broad per-service powers the demo stack genuinely needs to create/destroy.
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
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }

  # The hard boundary: IAM only within this project's namespace.
  statement {
    sid     = "IamWithinPrefix"
    effect  = "Allow"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/annotated-maps-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/annotated-maps-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/annotated-maps-*",
    ]
  }

  # Read the GitHub OIDC provider (the EKS module reads providers during plan).
  statement {
    sid       = "OidcProviderRead"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviders"]
    resources = ["*"]
  }

  # EKS/ELB/Autoscaling create service-linked roles on first use.
  statement {
    sid       = "ServiceLinkedRoles"
    effect    = "Allow"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/*"]
  }

  # State bucket: read-write (unlike the plan-only CI role).
  statement {
    sid     = "StateReadWrite"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.tf_state.arn,
      "${aws_s3_bucket.tf_state.arn}/*",
    ]
  }

  # Lifecycle events: this one topic, publish only.
  statement {
    sid       = "PublishAlerts"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  # The cost line in run-summary.
  statement {
    sid       = "CostRead"
    effect    = "Allow"
    actions   = ["ce:GetCostAndUsage"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deployer" {
  name   = "deploy-demo-stack"
  role   = aws_iam_role.deployer.id
  policy = data.aws_iam_policy_document.deployer_permissions.json
}
