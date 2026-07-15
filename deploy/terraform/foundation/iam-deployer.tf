# deploy/terraform/foundation/iam-deployer.tf
# The pipeline's apply-capable role (ADR-0010). Contrast with annotated-maps-ci
# (iam-ci.tf), which is read-only plan: this role CAN create and destroy the
# demo stack. Honest scoping: terraform apply of VPC+EKS+ECR legitimately
# needs broad service powers, so those are granted per-service, and the
# resource lists are narrowed where they can be: IAM to the annotated-maps-*
# prefix, S3 to the state bucket, SNS to the alerts topic.
#
# Read that as blast-radius control, NOT as a containment boundary: this role
# remains AdministratorAccess-EQUIVALENT within this account (it can create a
# role, attach AdministratorAccess, pass it to EC2, and read admin credentials
# off instance metadata). That is an accepted risk — the account is dedicated
# and disposable and the only trigger is maintainer-only — and ADR-0010
# discloses it in full. A permissions boundary is the real fix and is ticketed.
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

  # Blast-radius guard: IAM actions are confined to this project's resource
  # namespace, so a bug or a typo in the demo stack cannot touch unrelated
  # identities. This is NOT a security boundary against a malicious principal
  # holding this role — see the Deny below and ADR-0010's disclosure.
  statement {
    sid     = "IamWithinPrefix"
    effect  = "Allow"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/annotated-maps-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/annotated-maps-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/annotated-maps-*",
      # The EKS module creates the cluster's IRSA OIDC provider (enable_irsa =
      # true). Its ARN is oidc-provider/oidc.eks.<region>.amazonaws.com/id/<hash>
      # — it cannot carry the annotated-maps-* prefix, so scope it by issuer
      # host instead. This deliberately does NOT match the foundation's GitHub
      # provider (oidc-provider/token.actions.githubusercontent.com), so the
      # deployer cannot delete CI's trust anchor.
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/oidc.eks.*",
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

  # Closes the one-call self-escalation path: iam:* on role/annotated-maps-*
  # would otherwise match this role itself, letting it attach
  # AdministratorAccess to its own identity. The foundation stack that owns
  # this role is applied locally with operator credentials — the deployer
  # never needs to touch it. A Deny is unconditional; it beats any Allow, and
  # it is self-protecting (the role cannot PutRolePolicy away its own Deny).
  #
  # This does NOT close escalation — it raises its cost. Path B (create a role,
  # attach AdministratorAccess, pass it to EC2, read creds off IMDS) still
  # yields admin as a DIFFERENT principal, which can then strip this Deny.
  # One API call becomes ~4 plus an instance boot. Worth having — it is what
  # any scanner flags first — but see ADR-0010; the permissions boundary that
  # actually closes Path B is ticketed.
  statement {
    sid     = "NoSelfEscalation"
    effect  = "Deny"
    actions = ["iam:*"]
    # Resource reference, not a literal: a literal silently stops matching if
    # the role is ever renamed, reopening the path with no error. (An earlier
    # revision used a literal to "avoid a dependency cycle" — there is none;
    # assume_role_policy sources from a separate document, so role →
    # permissions doc → role policy is a DAG.)
    resources = [aws_iam_role.deployer.arn]
  }
}

resource "aws_iam_role_policy" "deployer" {
  name   = "deploy-demo-stack"
  role   = aws_iam_role.deployer.id
  policy = data.aws_iam_policy_document.deployer_permissions.json
}
