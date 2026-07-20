<!-- doc-status: dated -->

# Deployer permissions boundary — closing Path B (issue #109)

- Date: 2026-07-20
- Status: approved (design phase; implementation follows in the companion plan)
- Issue: #109 — "Deployer role: permissions boundary to close IAM privilege-escalation (Path B)"
- Supersedes-in-part: ADR-0010's Path-B acceptance (via new ADR-0012, see §7)
- Designed on: Claude Fable 5 (design phase). Implementation assigned to Opus per
  the project's model policy (design on Fable, implementation on Opus).

## 1. Problem

`annotated-maps-deployer` (`deploy/terraform/foundation/iam-deployer.tf`) is
AdministratorAccess-equivalent within account 675789572470. PR-D closed Path A
(self-attach admin) with the `NoSelfEscalation` Deny scoped to the deployer's
own ARN. **Path B remains open** and is disclosed as accepted in ADR-0010:

```
iam:CreateRole annotated-maps-x (trusting ec2.amazonaws.com)
  -> iam:AttachRolePolicy AdministratorAccess
  -> iam:CreateInstanceProfile + iam:AddRoleToInstanceProfile
  -> iam:PassRole + ec2:RunInstances
  -> admin credentials off instance metadata  =>  admin as a DIFFERENT principal
```

That different principal is untouched by `NoSelfEscalation` and can strip the
deployer's Deny. The genuine delta escalation buys (per ADR-0010): **guardrail
removal + persistence** — deleting the budget/SNS detector, deleting the
read-only CI role, or creating a role trusting an external AWS account that
survives revoking the GitHub OIDC trust.

**Fix**: an IAM permissions boundary. Deny the role-creating/granting actions
unless the request/target carries the boundary, so every role the deployer
creates is itself capped by the boundary's Allow-set.

## 2. Hard constraints (inherited, non-negotiable)

1. **Never broaden the deployer's IAM resource scope** — the `annotated-maps-*`
   prefix and the `aws-service-role/*` / `oidc.eks.*` carve-outs stay exactly as
   they are. New statements are Denys (which never broaden) or precise
   action additions; no resource-scope widening.
2. **Do not reintroduce the two live-run failures** recorded in
   `iam-deployer.tf`:
   - No blanket `iam:*` Deny anywhere. The EKS module's
     `data "aws_iam_session_context"` needs `iam:GetRole` on the deployer's own
     role; a blanket Deny killed the first live apply. All new Denys list
     precise mutating actions, or are conditioned.
   - The SLR path (`iam:CreateServiceLinkedRole` + `iam:GetRole` on
     `aws-service-role/*`) must keep working. `CreateServiceLinkedRole` is a
     distinct action from `CreateRole`, so the new Deny does not match it.
     Verified explicitly during review of the implementation.
3. **Teardown can never wedge.** Destroy-path actions (`iam:DetachRolePolicy`,
   `iam:DeleteRolePolicy`, `iam:DeleteRole`, `iam:DeleteInstanceProfile`, …)
   stay unconditioned — a role that somehow exists *without* the boundary must
   still be destroyable, or we recreate the stranded-billing failure mode this
   pipeline exists to prevent.
4. Static CI (`terraform validate`, `tflint`, `infra-plan`) passes on a boundary
   that would break the live cluster. **Correctness is only provable by a live
   apply/destroy cycle** — a user checkpoint (§8).

## 3. Design decisions (resolved with David, 2026-07-20)

| Question | Decision |
|---|---|
| Boundary Allow-set shape | **Service-level mirror** of the deployer's own `InfraServices` + exact ALB-policy extras (§4). Rejected: exact union of the three roles' policies (AWS mutates managed-policy contents server-side, so a frozen union rots and fails mid-apply/destroy on a live run); `NotAction` carve-out (cap spans every AWS service — needlessly loose). |
| Cross-stack wiring | **ARN by convention** (§6). `terraform_remote_state` is impossible: foundation state is *local* (`foundation/terraform.tfstate`, operator-applied); CI cannot read it. A `data "aws_iam_policy"` lookup would need a new `iam:GetPolicy` grant for no benefit — `permissions_boundary` is just an ARN string. |
| Does the deployer itself get the boundary? | **No.** It is created by the foundation stack with operator creds; capping it would force the boundary to include IAM/S3-state/SNS powers, defeating the boundary's tightness. Standard AWS delegation pattern: the condition on what it *creates* is the control; the deployer's own cap remains its identity policy + `NoSelfEscalation`, and only operator creds can mutate it. |
| ADR handling | **New ADR-0012** + a one-line Status-bullet pointer in ADR-0010. ADR-0010 is `doc-status: dated` (never edited to match current code, per ADR-0011); the Status bullet is lifecycle metadata the ADR template itself defines (`superseded by ADR-XXXX`), not a rewrite of the record. 0010's prose stays byte-identical. |
| Boundary policy name | `annotated-maps-boundary` — inside the prefix for naming consistency. The self-mutation hole this opens (deployer's `IamWithinPrefix` allows `iam:CreatePolicyVersion` on it) is closed by an explicit `BoundaryPolicyImmutable` Deny (§5). |

## 4. The boundary policy — `foundation/boundary.tf` (new file)

`aws_iam_policy` **`annotated-maps-boundary`**, created by the foundation stack
(operator creds). It is a **cap**, not a grant — a role capped by it has
`effective = boundary ∩ identity-policy`. Contents:

**Statement `InfraServices`** — mirror of the deployer's own non-IAM service
surface, on `*`:

```
ec2:*  eks:*  ecr:*  elasticloadbalancing:*  logs:*  autoscaling:*
kms:DescribeKey  kms:ListAliases
```

Security argument: a boundary-capped role can never exceed the service surface
the deployer itself already holds, so escalating through role-creation buys an
attacker (approximately) nothing they didn't have — see §4.1 for the exact
delta. Operational argument: any new action the EKS module or a bumped
node-group AMI needs *within these services* is already allowed, so module
version bumps don't break the live cluster.

**Statement `AlbControllerExtras`** — the exact actions in the vendored
`deploy/terraform/demo/policies/alb-controller-iam-policy.json` (v2.17.1) that
fall **outside** the six services above. Extract mechanically at implementation
time: parse the vendored JSON, drop every action whose service prefix is in
{ec2, eks, ecr, elasticloadbalancing, logs, autoscaling}, and Allow what
remains, verbatim, on `*`. Expected set (implementation re-derives; do not
trust this prose): `acm:DescribeCertificate`, `acm:ListCertificates`,
`cognito-idp:DescribeUserPoolClient`, `wafv2:GetWebACL`,
`wafv2:GetWebACLForResource`, `wafv2:AssociateWebACL`,
`wafv2:DisassociateWebACL`, `shield:GetSubscriptionState`,
`shield:DescribeProtection`, `shield:CreateProtection`,
`shield:DeleteProtection`.

**Statement `AlbControllerSlr`** — `iam:CreateServiceLinkedRole` with the same
condition the vendored policy carries
(`iam:AWSServiceName == elasticloadbalancing.amazonaws.com`). This is the only
`iam:` action in the boundary.

**Blocked by omission** (the point of the design): all other `iam:*` —
including `iam:PassRole`, so a capped role cannot chain to further principals —
`sns:*`, `budgets:*`, `s3:*` (state bucket unreachable), `ce:*`,
`organizations:*`, `sts:*`, and every service not listed. This kills every
enumerated Path-B delta: budget/SNS detector removal, boundary/Deny stripping,
and full-power external-trust persistence.

### 4.1 Honest deltas — where the cap exceeds or trails the deployer

- The boundary allows `acm`/`wafv2`/`shield`/`cognito-idp` actions the deployer
  itself does **not** hold (the ALB controller needs them at runtime). This is
  a small, enumerated, mostly-read/associate surface; state it in ADR-0012
  rather than let "mirror" overclaim.
- The boundary omits `sts:GetCallerIdentity` and `ce:GetCostAndUsage`, which
  the deployer holds. Deliberate: created roles don't need them.

## 5. Deployer policy changes — `foundation/iam-deployer.tf`

Four new **Deny** statements in `deployer_permissions`. Denys never broaden
scope; `NoSelfEscalation` is untouched (only its comment prose changes — it
currently says the boundary "is ticketed").

1. **`DenyRoleCreateWithoutBoundary`** — Deny `iam:CreateRole` on `*`,
   condition `StringNotEquals iam:PermissionsBoundary != <boundary ARN>`. An
   absent key satisfies `StringNotEquals`, so create-without-boundary is
   denied — the standard AWS delegation pattern. On `CreateRole` the condition
   key reflects the boundary **in the request**.
2. **`DenyGrantWithoutBoundary`** — Deny `iam:AttachRolePolicy` +
   `iam:PutRolePolicy` on `*`, same condition. On mutation actions the key
   reflects the boundary **attached to the target role**, so granting to any
   unbounded role is denied; granting to boundary-carrying roles (all three
   demo roles) succeeds. The demo stack's own calls under this Deny:
   the EKS module's managed-policy attaches to cluster/node roles (roles are
   created with the boundary before attachment — same resource graph), and
   `aws_iam_role_policy.alb_controller` (`PutRolePolicy` on a bounded role).
3. **`DenyBoundaryTamper`** — Deny `iam:DeleteRolePermissionsBoundary` on `*`
   unconditionally; Deny `iam:PutRolePermissionsBoundary` on `*` unless setting
   it *to* the canonical ARN (permits terraform's in-place boundary adoption on
   an existing role — the API sets the boundary via `PutRolePermissionsBoundary`
   when it isn't set at `CreateRole` time — while forbidding swaps to a
   different, looser boundary).
4. **`BoundaryPolicyImmutable`** — Deny `iam:CreatePolicyVersion`,
   `iam:DeletePolicyVersion`, `iam:SetDefaultPolicyVersion`, `iam:DeletePolicy`
   on the boundary policy's ARN. Without this, `IamWithinPrefix`'s
   `policy/annotated-maps-*` grant lets the deployer rewrite the boundary's
   default version — a one-call bypass of the entire design.

Implementation MUST verify against the IAM service authorization reference that
`iam:PermissionsBoundary` is a supported condition key for every action it is
attached to (it is documented for `CreateRole`/`AttachRolePolicy`/
`PutRolePolicy`/`PutRolePermissionsBoundary`); the live run (§8) is the final
proof.

### 5.1 Interaction check with existing statements

- `NoSelfEscalation` already denies `Put/DeleteRolePermissionsBoundary` **on the
  deployer's own ARN**. The new `DenyBoundaryTamper` covers all other roles.
  Overlap on the deployer's ARN is harmless (two Denys).
- The new Denys do not mention `iam:GetRole`/reads anywhere — the
  `aws_iam_session_context` scar stays healed.
- `iam:CreateServiceLinkedRole` (SLR scar) is not matched by any new Deny.
- Destroy path: `Detach`/`DeleteRolePolicy`/`DeleteRole` unconditioned (§2.3).

## 6. Demo-stack wiring — `deploy/terraform/demo/`

ARN by convention, no reads:

```hcl
# demo/ — locals (new small file or alongside existing data sources)
locals {
  # Created by foundation/boundary.tf; name is a cross-stack contract.
  deployer_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/annotated-maps-boundary"
}
```

(demo/ has no `data "aws_caller_identity"` today — verified 2026-07-20 — so
add it alongside the local.)

Three wiring points — every role the deployer creates:

| Role | File | Setting |
|---|---|---|
| EKS cluster role `annotated-maps-demo-cluster-*` | `demo/eks.tf`, `module "eks"` top level | `iam_role_permissions_boundary = local.deployer_boundary_arn` |
| Node role `annotated-maps-node*` | `demo/eks.tf`, `eks_managed_node_groups.default` | `iam_role_permissions_boundary = local.deployer_boundary_arn` |
| ALB IRSA role `annotated-maps-alb-controller` | `demo/iam-irsa.tf`, `aws_iam_role.alb_controller` | `permissions_boundary = local.deployer_boundary_arn` |

These three are the complete set: the VPC and ECR portions of the demo stack
create no IAM roles, and `enable_irsa` creates an OIDC *provider*, not a role.
If a future demo change adds a role without the boundary, `demo-up` fails
loudly at `CreateRole` — the Deny is self-enforcing, which is the desired
failure mode (deny at create, not silent gap).

Also: add `output "deployer_boundary_arn"` to `foundation/outputs.tf`
(symmetry with the other cross-referenced ARNs; documents the convention name
on the foundation side).

## 7. ADR-0012 + documentation

- **New `docs/adr/0012-deployer-permissions-boundary.md`** (house style: `#
  ADR-NNNN: title`, `- Status:` / `- Date:` bullets, Context / Decision /
  Consequences / Alternatives considered). Content: the boundary decision and
  Allow-set rationale (§3–§4), what is now **closed** (Path B proper: role
  creation without the cap, guardrail removal, Deny-stripping via a new
  principal), and the **honest residuals**:
  - A capped role trusting an external AWS account can still be created;
    persistence exists but is capped to the demo-service surface, cannot touch
    IAM/SNS/budgets/state, and the budget alarm — which no deployer-created
    principal can delete — remains the detector.
  - Cost abuse never needed escalation (`ec2:*` is granted outright) and is
    unchanged; the $10 budget alarm remains the real control on that axis.
  - The deployer can still delete `annotated-maps-ci` **directly** — that was
    never Path B (`IamWithinPrefix` allows it); recorded so ADR-0012 does not
    overclaim.
  - The `acm`/`wafv2`/`shield`/`cognito-idp` delta from §4.1.
- **ADR-0010**: change ONLY the Status bullet →
  `- Status: accepted; Path-B acceptance superseded by ADR-0012`. Prose stays
  byte-identical (dated-doc rule, ADR-0011).
- **`iam-deployer.tf` comments**: header (lines saying "A permissions boundary
  is the real fix and is ticketed") and the `NoSelfEscalation` closing comment
  ("the permissions boundary that actually closes Path B is ticketed") — update
  to point at ADR-0012 and the boundary as landed.
- Run `make docs-checks` before the PR (ADR-0011). Check ROADMAP.md for a
  Path-B/boundary line that this makes stale.
- PR uses `Closes #109`.

## 8. Rollout ordering and verification

**Ordering (load-bearing).** The Deny and the demo wiring must land in the
right sequence:

1. PR merges (foundation `.tf` + demo `.tf` + ADR-0012 + doc updates). Merging
   changes no live IAM — foundation is operator-applied.
2. David applies `foundation/` locally with operator creds: boundary policy +
   four Denys land atomically. Safe while the demo is down (it always is
   between runs). From this moment old demo code could no longer create roles —
   but the merged demo code already carries the wiring, so the window where
   `demo-up` would fail cannot occur if step 1 precedes step 2.
3. Live verification checkpoint (below), then teardown.

**Rollback**: revert the foundation apply locally (removes the Denys) —
instant, no demo impact. Do not delete the boundary policy while a live
cluster's roles reference it; with the demo down there is no referencing role.

**Static gates** (`terraform validate`, `tflint`, `make docs-checks`, the
`infra-plan` CI job) all pass on a boundary that would break the live cluster —
they gate syntax and diff sanity only. The `infra-plan` read-only role needs no
new permissions (no new data sources; `permissions_boundary` is a string).

**Live verification — USER CHECKPOINT with David (final gate, ~$1–2, ~30 min,
never left up):**

1. `make demo-up` — full apply. Exercises `CreateRole`×3 under the new Deny
   (positive path), managed-policy attaches to bounded roles, `PutRolePolicy`
   on the bounded ALB role, and the SLR + session-context scars.
2. Runtime proof the caps are not too tight: cluster Active, 2 nodes Ready
   (node role works: worker/CNI/ECR-read under boundary), app reachable through
   the ALB (controller provisioned listeners/target-groups under boundary —
   the IRSA role doing real work).
3. `aws iam get-role` on all three roles → each shows
   `PermissionsBoundary = annotated-maps-boundary`.
4. `make demo-down` — full destroy to zero (destroy-path unconditioned; the
   stranded-billing check). Then the billable-resource sweep per repo protocol.

Optional negative test (nice-to-have, not a gate): from a pipeline shell as the
deployer, `aws iam create-role` *without* `--permissions-boundary` and confirm
`AccessDenied`; the positive path plus standard Deny semantics is the required
evidence.

## 9. Out of scope

- Bounding the deployer role itself (§3) or the read-only `annotated-maps-ci`
  role (creates nothing).
- Any change to the GitHub OIDC trust, Environment protection, or workflow
  triggers (ADR-0010's standing constraints continue unchanged).
- SCPs / new detective controls (single-account setup; the budget alarm
  remains the detector).
