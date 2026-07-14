# deploy/terraform/foundation/iam-ci.tf
# GitHub Actions -> AWS via OIDC federation. No access keys exist for CI.
# The role can PLAN (read-only), never APPLY: the apply pipeline is
# Milestone 4's story and will get its own, separately-scoped role.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # GitHub's OIDC root CA thumbprint. AWS now validates against trusted CAs
  # and largely ignores this, but the argument is required.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "ci_trust" {
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

    # Only a job that declares `environment: aws-plan` gets this sub, and
    # that Environment has a required-reviewer rule, so fork PRs pause for
    # human approval before any token is issued — fork-safe while allowing
    # plan-on-PR.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:dcltdw/annotated-maps-sp:environment:aws-plan"]
    }
  }
}

resource "aws_iam_role" "ci" {
  name               = "annotated-maps-ci"
  assume_role_policy = data.aws_iam_policy_document.ci_trust.json
}

data "aws_iam_policy_document" "ci_plan_readonly" {
  # terraform plan needs to READ current state of everything the stack
  # manages, and the state bucket. Nothing here can create/modify/delete.
  statement {
    sid    = "DescribeInfra"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "eks:Describe*",
      "eks:List*",
      "ecr:Describe*",
      "ecr:List*",
      "ecr:GetLifecyclePolicy",
      "ecr:GetRepositoryPolicy",
      "iam:Get*",
      "iam:List*",
      "budgets:ViewBudget",
      "logs:Describe*",
      "kms:DescribeKey",
      "kms:GetKeyPolicy",
      "kms:GetKeyRotationStatus",
      "kms:ListResourceTags",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "StateBucketRead"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::annotated-maps-tf-state-*",
      "arn:aws:s3:::annotated-maps-tf-state-*/*",
    ]
  }
}

resource "aws_iam_role_policy" "ci_plan_readonly" {
  name   = "plan-readonly"
  role   = aws_iam_role.ci.id
  policy = data.aws_iam_policy_document.ci_plan_readonly.json
}
