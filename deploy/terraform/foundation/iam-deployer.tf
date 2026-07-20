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
# discloses it in full. The permissions boundary that closes Path B is now
# implemented (boundary.tf + the Deny block below; issue #109, ADR-0012).
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

  # EKS/ELB/Autoscaling create service-linked roles on first use — and READ
  # them before creating. The first live node-group create failed with:
  #   InvalidRequestException: Failed to validate if SLR:
  #   AWSServiceRoleForAmazonEKSNodegroup already exists due to missing
  #   permissions for 'iam:GetRole'
  # EKS checks whether the SLR exists before deciding to create it, so
  # create-without-read is a broken half-grant. iam:GetRole here is scoped to
  # the aws-service-role/ path only; roles this stack owns are already readable
  # via IamWithinPrefix, so between the two every role terraform must read is
  # covered — and nothing outside those two paths is.
  statement {
    sid    = "ServiceLinkedRoles"
    effect = "Allow"
    actions = [
      "iam:CreateServiceLinkedRole",
      "iam:GetRole",
    ]
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
  # never needs to MUTATE it. A Deny is unconditional; it beats any Allow, and
  # it is self-protecting (the role cannot PutRolePolicy away its own Deny).
  #
  # MUTATING ACTIONS ONLY — deliberately not iam:*. The first live run proved
  # why: the EKS module's `data "aws_iam_session_context" "current"` resolves
  # the CALLER's own STS source role (for cluster_creator_admin_permissions),
  # which needs iam:GetRole on THIS role. A blanket iam:* Deny failed the apply
  # with "AccessDenied ... with an explicit deny in an identity-based policy"
  # before a single resource was created. Reads don't escalate; mutations do.
  # An Allow cannot carve an exception out of a Deny, so the action list itself
  # has to be precise. Every action below is one that either grants this role
  # more power or removes this very Deny.
  #
  # This does NOT close escalation — it raises its cost. Path B (create a role,
  # attach AdministratorAccess, pass it to EC2, read creds off IMDS) still
  # yields admin as a DIFFERENT principal, which can then strip this Deny.
  # One API call becomes ~4 plus an instance boot. Worth having — it is what
  # any scanner flags first — but see ADR-0010. The permissions boundary that
  # actually closes Path B is implemented in boundary.tf and the DenyRoleCreate
  # WithoutBoundary/DenyGrantWithoutBoundary statements below (ADR-0012).
  statement {
    sid    = "NoSelfEscalation"
    effect = "Deny"
    actions = [
      # Grant itself more permissions
      "iam:AttachRolePolicy",
      "iam:PutRolePolicy",
      # Remove this Deny
      "iam:DetachRolePolicy",
      "iam:DeleteRolePolicy",
      # Widen its own trust to admit new principals
      "iam:UpdateAssumeRolePolicy",
      # Escape the permissions boundary (the Path-B fix, now in boundary.tf)
      "iam:PutRolePermissionsBoundary",
      "iam:DeleteRolePermissionsBoundary",
      # Delete-and-recreate itself with a fresh policy
      "iam:DeleteRole",
      "iam:CreateRole",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
    ]
    # Resource reference, not a literal: a literal silently stops matching if
    # the role is ever renamed, reopening the path with no error. (An earlier
    # revision used a literal to "avoid a dependency cycle" — there is none;
    # assume_role_policy sources from a separate document, so role →
    # permissions doc → role policy is a DAG.)
    resources = [aws_iam_role.deployer.arn]
  }

  # --- Path B closure (issue #109, ADR-0012) --------------------------------
  # NoSelfEscalation above stops the deployer escalating ITSELF. These force a
  # permissions boundary onto every role the deployer CREATES, so laundering
  # into a new admin role (Path B) is capped to the demo's service surface —
  # no iam:*, no sns/budgets/s3, so it cannot strip a Deny or delete a
  # guardrail. Precise mutating actions only — never iam:* — so iam:GetRole
  # (the aws_iam_session_context scar) and iam:CreateServiceLinkedRole (the SLR
  # scar) stay allowed by the statements above.

  # Every role the deployer creates must be born under the boundary. An absent
  # iam:PermissionsBoundary key satisfies StringNotEquals, so a CreateRole that
  # omits the boundary is denied. This is the AWS-documented delegation pattern.
  statement {
    sid       = "DenyRoleCreateWithoutBoundary"
    effect    = "Deny"
    actions   = ["iam:CreateRole"]
    resources = ["*"]
    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.deployer_boundary.arn]
    }
  }

  # Granting permissions to a role that lacks the boundary is denied. On these
  # actions iam:PermissionsBoundary reflects the TARGET role's attached
  # boundary, so empowering any non-bounded role is blocked; the three demo
  # roles carry the boundary, so their legitimate grants still succeed.
  statement {
    sid       = "DenyGrantWithoutBoundary"
    effect    = "Deny"
    actions   = ["iam:AttachRolePolicy", "iam:PutRolePolicy"]
    resources = ["*"]
    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.deployer_boundary.arn]
    }
  }

  # Removing a role's boundary is never legitimate for this stack. Unconditional
  # Deny (NoSelfEscalation already covers the deployer's own ARN; this covers
  # every other role).
  statement {
    sid       = "DenyBoundaryRemoval"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["*"]
  }

  # Setting/replacing a boundary is allowed ONLY to the canonical ARN, so
  # terraform can adopt the boundary on a role that didn't get it at
  # CreateRole time, but a swap to a weaker boundary is denied.
  statement {
    sid       = "DenyBoundarySwap"
    effect    = "Deny"
    actions   = ["iam:PutRolePermissionsBoundary"]
    resources = ["*"]
    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.deployer_boundary.arn]
    }
  }

  # The boundary policy is named inside the annotated-maps-* prefix, so
  # IamWithinPrefix would otherwise let the deployer rewrite its default version
  # — a one-call bypass of this entire design. Deny editing it.
  statement {
    sid    = "BoundaryPolicyImmutable"
    effect = "Deny"
    actions = [
      "iam:CreatePolicyVersion",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
      "iam:DeletePolicy",
    ]
    resources = [aws_iam_policy.deployer_boundary.arn]
  }
}

resource "aws_iam_role_policy" "deployer" {
  name   = "deploy-demo-stack"
  role   = aws_iam_role.deployer.id
  policy = data.aws_iam_policy_document.deployer_permissions.json
}
