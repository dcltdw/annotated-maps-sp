<!-- doc-status: dated -->

# ADR-0012: A permissions boundary closes Path B on the deployer role

- Status: accepted
- Date: 2026-07-20

## Context

ADR-0010 shipped the demo pipeline's apply role, `annotated-maps-deployer`,
and disclosed it as AdministratorAccess-equivalent within account
675789572470 via an open escalation it called **Path B**: the deployer can
`iam:CreateRole` a new `annotated-maps-*` role, attach `AdministratorAccess`
to it, put it on an EC2 instance, and read admin credentials off instance
metadata — yielding admin as a *different* principal that the deployer's
`NoSelfEscalation` Deny does not cover. ADR-0010 accepted this and ticketed
the real fix (issue #109): a permissions boundary. This ADR is that fix.

## Decision

Add an IAM permissions boundary, `annotated-maps-boundary`
(`deploy/terraform/foundation/boundary.tf`), and force it onto every role the
deployer creates. A boundary caps a role's *effective* permissions to the
intersection of its own policies and the boundary, so a created role with
`AdministratorAccess` attached is still confined to the boundary's Allow-set.

**Boundary Allow-set — a service-level mirror.** It allows the same broad
service families the deployer itself holds (`ec2:*`, `eks:*`, `ecr:*`,
`elasticloadbalancing:*`, `logs:*`, `autoscaling:*`, plus two read-only KMS
actions), plus exactly the out-of-family actions the vendored ALB-controller
policy needs, plus the one `elasticloadbalancing` service-linked-role create.
A capped role therefore never exceeds the deployer's own service surface, so
laundering into it buys nothing; drawing the ceiling at the service level
keeps the cluster working across EKS-module and node-AMI version bumps. The
alternatives (an exact copy of the three roles' managed policies, which rots
as AWS mutates them server-side and fails mid-apply/destroy; or an allow-all
`NotAction` denylist, which spans every AWS service) were rejected — see
Alternatives.

**Forcing the boundary on.** Five Deny statements on the deployer
(`iam-deployer.tf`): `DenyRoleCreateWithoutBoundary` and
`DenyGrantWithoutBoundary` (deny `CreateRole`/`AttachRolePolicy`/
`PutRolePolicy` unless `iam:PermissionsBoundary` equals the canonical ARN —
the AWS-documented delegation pattern), `DenyBoundaryRemoval` and
`DenyBoundarySwap` (no removing or weakening a role's boundary), and
`BoundaryPolicyImmutable` (the deployer cannot rewrite the boundary policy's
own contents — necessary because the policy is named inside the editable
`annotated-maps-*` prefix). All list precise actions, never `iam:*`, so the
`iam:GetRole` (session-context) and `iam:CreateServiceLinkedRole` reads two
prior live runs proved necessary stay allowed.

**The deployer itself is not boundary-capped.** It is created by the
foundation stack with operator creds; capping it would force the boundary to
include the IAM/state/SNS powers the deployer legitimately needs, defeating a
tight boundary. This is the standard delegation shape: the control is the
delegator being forced to cap what it delegates, not a cap on the delegator.

**Honest deltas (the mirror is not exact).**

- The boundary allows a small out-of-family surface the deployer does *not*
  itself hold, because the ALB controller needs it at runtime: `acm` reads,
  `cognito-idp:DescribeUserPoolClient`, `shield:*` (4), `waf-regional:*` (4),
  `wafv2:*` (4), and — correcting the design spec's "the only iam: action is
  CreateServiceLinkedRole" — **`iam:GetServerCertificate` and
  `iam:ListServerCertificates`** (IAM reads for TLS certs stored in IAM).
  These were re-derived mechanically from the vendored policy
  (`alb-controller-iam-policy.json`, v2.17.1); re-derive if it is re-vendored.
- The boundary omits `sts:GetCallerIdentity` and `ce:GetCostAndUsage`, which
  the deployer holds but created roles do not need.

## Consequences

- **Path B is closed.** A deployer-created role can no longer exceed the
  demo's service surface: no `iam:*` (so it cannot strip a Deny), no
  `sns:`/`budgets:`/`s3:` (so it cannot delete the budget/SNS detector or
  reach state), no `iam:PassRole` (so it cannot chain onward). The
  one-call boundary-rewrite bypass is closed by `BoundaryPolicyImmutable`.
- **Residual — capped persistence.** A role trusting an external account can
  still be *created*, but capped to the service surface; it cannot touch IAM,
  SNS, budgets, or state, and the budget alarm — which no deployer-created
  principal can now delete — remains the detector. Persistence is possible but
  declawed.
- **Cost abuse is unchanged** — `ec2:*` is granted to the deployer outright,
  never required escalation, and the $10 budget alarm remains the real control
  on that axis. This ADR does not touch it.
- **The read-only `annotated-maps-ci` role can still be deleted directly** by
  the deployer (`IamWithinPrefix` already allows it) — that was never Path B,
  and this ADR does not close it.
- **Verification is split by principal** (see the #109 plan): local
  `make demo-up` runs as the operator and proves the boundary ceiling does not
  break the cluster; `aws iam simulate-principal-policy` against the deployer
  proves the Denys bite. The account was proven end-to-end by a live
  apply/destroy cycle plus the simulator matrix before this ADR moved to
  accepted.

## Alternatives considered

- **Exact copy of the three roles' managed policies as the boundary.**
  Tightest ceiling, but AWS updates managed-policy contents server-side, so a
  frozen copy rots and fails as a mid-apply or mid-destroy `AccessDenied` — the
  stranded-billing failure the pipeline exists to prevent.
- **Allow-all `NotAction` denylist boundary.** Break-proof for the cluster,
  but the ceiling would span every AWS service — a weak boundary in a project
  whose point is IAM rigor.
- **Capping the deployer role itself.** Rejected — see Decision; it would
  force a loose boundary and defeat the purpose.
