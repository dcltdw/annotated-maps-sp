# Deployer Permissions Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Path B privilege-escalation on the `annotated-maps-deployer` role by adding an IAM permissions boundary that caps every role the deployer creates, plus the Deny statements that force that boundary onto those roles.

**Architecture:** A new `annotated-maps-boundary` managed policy (foundation stack) is a *ceiling* — every role the deployer creates has `effective = its-policies ∩ boundary`. Five new Deny statements on the deployer forbid creating/empowering any role that does not carry the boundary, and forbid tampering with the boundary. The demo stack attaches the boundary to the three roles it creates (EKS cluster role, node role, ALB-controller IRSA role) via the boundary's ARN, resolved by naming convention across the two stacks.

**Tech Stack:** Terraform (`>= 1.10`, AWS provider `~> 5.0`), `terraform-aws-modules/eks/aws ~> 20.0`, the AWS IAM policy simulator for behavioral verification, `make demo-up`/`demo-down` for the live apply/destroy cycle.

**Source spec:** [docs/superpowers/specs/2026-07-20-deployer-permissions-boundary-design.md](../specs/2026-07-20-deployer-permissions-boundary-design.md). Read it first. This plan implements it and records three deliberate refinements found while planning (see Global Constraints).

## Global Constraints

Every task's requirements implicitly include these:

- **Model policy:** implementation runs on **Opus** (design was Fable). The final live checkpoint (Task 5) is a **user checkpoint with David** — Opus drives, David authorizes/watches and provides operator credentials.
- **Never broaden the deployer's IAM resource scope.** The `annotated-maps-*` prefix and the `aws-service-role/*` / `oidc.eks.*` carve-outs in `iam-deployer.tf` stay byte-identical. New statements are Denys (which never broaden) only. No resource-scope widening anywhere.
- **No blanket `iam:*` Deny, ever.** Two live-run scars in `iam-deployer.tf` prove why: (a) the EKS module's `data "aws_iam_session_context"` needs `iam:GetRole` on the deployer's own role; (b) the ALB controller's SLR path needs `iam:CreateServiceLinkedRole`. Every new Deny lists precise actions and none of them match `iam:GetRole` or `iam:CreateServiceLinkedRole`.
- **Destroy path stays unconditioned.** Do not add conditions to `iam:DeleteRole`, `iam:DetachRolePolicy`, `iam:DeleteRolePolicy`, `iam:DeleteInstanceProfile`, etc. A role that somehow exists without a boundary must still be destroyable, or teardown wedges (the stranded-billing failure the pipeline exists to prevent).
- **Terraform version:** exactly `1.15.8` in CI (`hashicorp/setup-terraform@v3`); local `>= 1.10`. **tflint** `v0.63.1`. **Account:** `675789572470`, region `us-east-1`.
- **Boundary policy name is a cross-stack contract:** exactly `annotated-maps-boundary` → ARN `arn:aws:iam::675789572470:policy/annotated-maps-boundary`. The demo stack hardcodes this name by convention (foundation state is local/operator-only, so `terraform_remote_state` cannot reach it).

**Three refinements to the spec, found while planning (carry them into ADR-0012):**

1. **ALB out-of-family actions, mechanically re-derived from the vendored policy** (`deploy/terraform/demo/policies/alb-controller-iam-policy.json`, v2.17.1), differ from the spec's *guessed* list (the spec explicitly said "re-derive; do not trust the prose"). The real set additionally includes **`waf-regional:*`** (4 actions) and **`iam:GetServerCertificate` + `iam:ListServerCertificates`**. So the boundary allows **two IAM read actions beyond `CreateServiceLinkedRole`** — the spec's "the only iam: action in the boundary" claim is corrected here.
2. **The spec's "four Deny statements" become five HCL statements.** "DenyBoundaryTamper" is split into `DenyBoundaryRemoval` (unconditional Deny of `DeleteRolePermissionsBoundary`) and `DenyBoundarySwap` (conditional Deny of `PutRolePermissionsBoundary` unless set to the canonical ARN), because one statement cannot both deny-unconditionally and deny-conditionally. Four logical protections, five statements.
3. **Verification is split by principal.** Local `make demo-up` runs `terraform apply` as the **operator**, not as the deployer (the deployer's trust policy only admits GitHub OIDC; operators cannot `AssumeRole` into it). So `demo-up` proves the boundary *ceiling doesn't break the cluster* (property 1), but it does **not** exercise the deployer's new Denys. Those (property 2) are proven with `aws iam simulate-principal-policy` against the deployer role. See Task 5.

---

## File Structure

- `deploy/terraform/foundation/boundary.tf` **(new)** — the `annotated-maps-boundary` managed policy (the ceiling).
- `deploy/terraform/foundation/outputs.tf` **(modify)** — export the boundary ARN (documents the cross-stack contract on the producing side).
- `deploy/terraform/foundation/iam-deployer.tf` **(modify)** — five new Deny statements; update three stale "ticketed" comments.
- `deploy/terraform/demo/boundary.tf` **(new)** — `aws_caller_identity` + the `deployer_boundary_arn` local (by-convention ARN).
- `deploy/terraform/demo/eks.tf` **(modify)** — `iam_role_permissions_boundary` on the cluster role and the node group.
- `deploy/terraform/demo/iam-irsa.tf` **(modify)** — `permissions_boundary` on the ALB-controller role.
- `docs/adr/0012-deployer-permissions-boundary.md` **(new)** — the boundary decision + residuals.
- `docs/adr/0010-pipeline-apply-role.md` **(modify)** — Status bullet only (lifecycle metadata; prose stays byte-identical).

**Verification design (per task):** Terraform is declarative config, so there is no pytest-style "failing test first." Each code task's test cycle is **`terraform fmt -check` → `validate` → `tflint`** (the exact commands CI runs), plus an explicit inspection assertion. The *behavioral* proof — that the Denys bite and the cluster still works — is Task 5, the live checkpoint, exactly as the spec requires. Static gates pass on a boundary that would break the cluster; only Task 5 proves correctness.

**Starting state:** branch off current `main`.

```bash
git checkout main && git pull --ff-only
git checkout -b issue-109-permissions-boundary
```

---

### Task 1: The boundary policy (the ceiling) + its exported ARN

**Files:**
- Create: `deploy/terraform/foundation/boundary.tf`
- Modify: `deploy/terraform/foundation/outputs.tf`

**Interfaces:**
- Produces: `aws_iam_policy.deployer_boundary` (foundation stack) with `.arn` = `arn:aws:iam::675789572470:policy/annotated-maps-boundary`. Task 2 references `aws_iam_policy.deployer_boundary.arn` directly (same stack). The demo stack (Task 3) reconstructs the same ARN by convention.

- [ ] **Step 1: Re-derive the ALB out-of-family action list mechanically (do not hand-type it)**

Run this and use its output verbatim in Step 2 — it is the source of truth, not the prose below it:

```bash
cd "$(git rev-parse --show-toplevel)"
python3 - <<'PY'
import json
d = json.load(open("deploy/terraform/demo/policies/alb-controller-iam-policy.json"))
infra = {"ec2","eks","ecr","elasticloadbalancing","logs","autoscaling"}
acts = set()
for st in d["Statement"]:
    a = st.get("Action", [])
    acts.update([a] if isinstance(a, str) else a)
extras = sorted(a for a in acts if a.split(":")[0] not in infra and a != "iam:CreateServiceLinkedRole")
print("AlbControllerExtras actions:")
for a in extras: print(f'      "{a}",')
PY
```

Expected output (17 actions — if it differs, the vendored policy changed; use the actual output and note it in Task 4's ADR):

```
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
```

- [ ] **Step 2: Write `deploy/terraform/foundation/boundary.tf`**

```hcl
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
```

- [ ] **Step 3: Append the boundary ARN output to `deploy/terraform/foundation/outputs.tf`**

Add (do not remove the existing four outputs):

```hcl

output "deployer_boundary_arn" {
  value = aws_iam_policy.deployer_boundary.arn
}
```

- [ ] **Step 4: Static gates — fmt, validate, tflint (foundation)**

```bash
cd "$(git rev-parse --show-toplevel)"
terraform fmt -check -recursive deploy/terraform
terraform -chdir=deploy/terraform/foundation init -backend=false
terraform -chdir=deploy/terraform/foundation validate
tflint --chdir=deploy/terraform/foundation
```

Expected: `fmt` prints nothing (exit 0); `validate` → `Success! The configuration is valid.`; `tflint` prints nothing (exit 0). If `fmt` lists the new file, run `terraform fmt -recursive deploy/terraform` and re-check.

- [ ] **Step 5: Commit**

```bash
git add deploy/terraform/foundation/boundary.tf deploy/terraform/foundation/outputs.tf
git commit -m "feat(iam): add annotated-maps-boundary permissions boundary policy

The ceiling for every role the deployer creates (issue #109). Service-level
mirror of the deployer's InfraServices + the mechanically-derived ALB
out-of-family actions (incl. waf-regional + iam:*ServerCertificate reads) +
the elasticloadbalancing SLR. Exported as deployer_boundary_arn.

Refs #109

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Force the boundary onto everything the deployer creates (the Denys)

**Files:**
- Modify: `deploy/terraform/foundation/iam-deployer.tf` (add statements to `data "aws_iam_policy_document" "deployer_permissions"`, before its closing `}`; update three comments)

**Interfaces:**
- Consumes: `aws_iam_policy.deployer_boundary.arn` from Task 1.
- Produces: nothing new for later tasks (Task 5 verifies these via the simulator).

- [ ] **Step 1: Add the five Deny statements**

Insert these five statements inside `data "aws_iam_policy_document" "deployer_permissions"`, immediately **after** the existing `NoSelfEscalation` statement and before the document's closing brace. Do not modify any existing statement.

```hcl

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
```

- [ ] **Step 2: Update the three stale "ticketed" comments to reflect the boundary now existing**

The boundary is no longer "ticketed" — leaving those words would be a false statement in the code. Make these exact replacements in `iam-deployer.tf`:

Replace (near the top-of-file header, ~line 14):
```
# discloses it in full. A permissions boundary is the real fix and is ticketed.
```
with:
```
# discloses it in full. The permissions boundary that closes Path B is now
# implemented (boundary.tf + the Deny block below; issue #109, ADR-0012).
```

Replace (in the `NoSelfEscalation` comment, ~lines 168-169):
```
  # any scanner flags first — but see ADR-0010; the permissions boundary that
  # actually closes Path B is ticketed.
```
with:
```
  # any scanner flags first — but see ADR-0010. The permissions boundary that
  # actually closes Path B is implemented in boundary.tf and the DenyRoleCreate
  # WithoutBoundary/DenyGrantWithoutBoundary statements below (ADR-0012).
```

Replace (in the `NoSelfEscalation` action-list comment, ~line 182):
```
      # Escape a permissions boundary (the ticketed Path-B fix) once one exists
```
with:
```
      # Escape the permissions boundary (the Path-B fix, now in boundary.tf)
```

- [ ] **Step 3: Static gates — fmt, validate, tflint (foundation)**

```bash
cd "$(git rev-parse --show-toplevel)"
terraform fmt -check -recursive deploy/terraform
terraform -chdir=deploy/terraform/foundation init -backend=false
terraform -chdir=deploy/terraform/foundation validate
tflint --chdir=deploy/terraform/foundation
```

Expected: all clean (as Task 1 Step 4).

- [ ] **Step 4: Inspection assertion — confirm no blanket `iam:*` Deny and scars untouched**

```bash
# The new Denys must NOT contain iam:* or match GetRole/CreateServiceLinkedRole.
grep -n 'iam:\*' deploy/terraform/foundation/iam-deployer.tf   # expect: only the two ALLOW statements (IamWithinPrefix), NOT inside any Deny
grep -n 'CreateServiceLinkedRole\|GetRole' deploy/terraform/foundation/iam-deployer.tf  # expect: only in the ServiceLinkedRoles ALLOW statement
```
Expected: `iam:*` appears only in the `IamWithinPrefix` Allow (unchanged); `GetRole`/`CreateServiceLinkedRole` appear only in the `ServiceLinkedRoles` Allow (unchanged). No Deny statement contains any of them.

- [ ] **Step 5: Commit**

```bash
git add deploy/terraform/foundation/iam-deployer.tf
git commit -m "feat(iam): force the boundary onto every deployer-created role

Five Deny statements close Path B: DenyRoleCreateWithoutBoundary,
DenyGrantWithoutBoundary, DenyBoundaryRemoval, DenyBoundarySwap,
BoundaryPolicyImmutable. Precise actions only — no blanket iam:* — so the
GetRole (session-context) and CreateServiceLinkedRole scars stay open. Also
updates the now-stale 'ticketed' comments.

Refs #109

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Attach the boundary to the three demo-created roles

**Files:**
- Create: `deploy/terraform/demo/boundary.tf`
- Modify: `deploy/terraform/demo/eks.tf` (module top-level + node group)
- Modify: `deploy/terraform/demo/iam-irsa.tf` (ALB role)

**Interfaces:**
- Consumes: the boundary ARN by convention (foundation's `annotated-maps-boundary`).
- Produces: `local.deployer_boundary_arn` used by `eks.tf` and `iam-irsa.tf`.

- [ ] **Step 1: Write `deploy/terraform/demo/boundary.tf`**

```hcl
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
```

- [ ] **Step 2: Add the boundary to the EKS cluster role (module top level) in `deploy/terraform/demo/eks.tf`**

Inside `module "eks"`, add this line at the top level of the module block (e.g. right after `cluster_version = "1.33"`):

```hcl
  # Cap the module-created cluster role under the deployer's permissions
  # boundary (issue #109); without it the deployer's CreateRole is denied.
  iam_role_permissions_boundary = local.deployer_boundary_arn
```

- [ ] **Step 3: Add the boundary to the node group in `deploy/terraform/demo/eks.tf`**

Inside `eks_managed_node_groups.default`, add (e.g. right after the `iam_role_use_name_prefix = true` line):

```hcl
      # Same boundary on the node role the module creates (issue #109).
      iam_role_permissions_boundary = local.deployer_boundary_arn
```

- [ ] **Step 4: Add the boundary to the ALB-controller role in `deploy/terraform/demo/iam-irsa.tf`**

In `resource "aws_iam_role" "alb_controller"`, add a `permissions_boundary` argument:

```hcl
resource "aws_iam_role" "alb_controller" {
  name                 = "annotated-maps-alb-controller"
  assume_role_policy   = data.aws_iam_policy_document.alb_controller_trust.json
  permissions_boundary = local.deployer_boundary_arn # issue #109
}
```

- [ ] **Step 5: Static gates — fmt, validate, tflint (demo)**

```bash
cd "$(git rev-parse --show-toplevel)"
terraform fmt -check -recursive deploy/terraform
terraform -chdir=deploy/terraform/demo init -backend=false
terraform -chdir=deploy/terraform/demo validate
tflint --chdir=deploy/terraform/demo
```

Expected: all clean. `validate` → `Success! The configuration is valid.` (This confirms the module accepts `iam_role_permissions_boundary` at both the top level and in the node group, and that `local.deployer_boundary_arn` resolves.)

- [ ] **Step 6: Commit**

```bash
git add deploy/terraform/demo/boundary.tf deploy/terraform/demo/eks.tf deploy/terraform/demo/iam-irsa.tf
git commit -m "feat(demo): attach the deployer boundary to all three created roles

EKS cluster role, node role, and the ALB-controller IRSA role now carry
annotated-maps-boundary (ARN resolved by naming convention across stacks).
These are the complete set of roles the demo stack creates.

Refs #109

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: ADR-0012, ADR-0010 status pointer, docs gate

**Files:**
- Create: `docs/adr/0012-deployer-permissions-boundary.md`
- Modify: `docs/adr/0010-pipeline-apply-role.md` (Status bullet only)

**Interfaces:** none (documentation).

- [ ] **Step 1: Write `docs/adr/0012-deployer-permissions-boundary.md`** (house style: `# ADR-NNNN: title`, `- Status:`/`- Date:` bullets, Context / Decision / Consequences / Alternatives considered)

```markdown
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
```

- [ ] **Step 2: Update ONLY the Status bullet of `docs/adr/0010-pipeline-apply-role.md`**

ADR-0010 is `doc-status: dated` — its prose is never edited to match new code. Changing the Status bullet is ADR lifecycle metadata (the template defines `superseded by ADR-XXXX` as a legal status), not a prose rewrite. Make exactly this one change:

Replace:
```
- Status: accepted
```
with:
```
- Status: accepted; Path-B acceptance superseded by ADR-0012
```

Do not touch any other line in ADR-0010.

- [ ] **Step 3: Docs gate**

```bash
cd "$(git rev-parse --show-toplevel)"
make docs-checks
```

Expected: `Doc link check passed` and `Doc facts check passed`. (ADR-0012 is `# ADR-0012:` house style; it declares no `doc-status` marker requirement failure because ADRs are in status scope — if the checker reports a missing marker for a *living* ADR, note that existing ADRs 0001-0011 all carry `<!-- doc-status: dated -->` on line 1; add the same marker line to 0012 as its first line and re-run. Match the existing ADRs exactly.)

- [ ] **Step 4: Commit**

```bash
git add docs/adr/0012-deployer-permissions-boundary.md docs/adr/0010-pipeline-apply-role.md
git commit -m "docs(adr): ADR-0012 records the boundary; ADR-0010 status points to it

ADR-0012 documents the Path-B closure, the service-mirror Allow-set with its
honest deltas (incl. the waf-regional + iam:*ServerCertificate corrections to
the spec), the five Denys, and the residuals. ADR-0010's Status bullet now
points forward; its dated prose is unchanged.

Refs #109

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: USER CHECKPOINT — live verification, then merge

> **This is a checkpoint with David.** Opus drives; David authorizes, supplies operator credentials, and watches. Cost ~$1–2, ~30 min, **never left running**. This is the only gate that proves correctness — every static check passes on a boundary that breaks the cluster.

**Files:** none (verification + `Closes #109`).

- [ ] **Step 1: Open the PR (do not merge yet)**

Push the branch and open a PR against `main` with the repo's required headings (`## Summary`, `## Provenance`, `## Reasoning`, `## Testing`, `## Risk & rollback`). Use **`Closes #109`** in the body so the merge auto-closes the issue (this is the implementation, unlike the design-docs PR which used `Refs`). Note in the PR that CI's `infra-plan` job will run a read-only `terraform plan` of the demo stack (reviewer-gated `aws-plan` environment) — that plan should show the three roles gaining `permissions_boundary` and requires no new CI-role permissions.

- [ ] **Step 2: David applies the foundation stack from the branch (operator creds)**

```bash
cd deploy/terraform/foundation
terraform init
terraform apply    # REVIEW the plan: creates aws_iam_policy.annotated-maps-boundary;
                   # updates the deployer role policy to add the 5 Deny statements.
                   # No other resource should change.
```

Applying from the branch verifies before merge. If verification fails, `terraform apply` after reverting the branch changes restores the prior state (rollback is instant; the demo is down, so nothing references the boundary yet).

- [ ] **Step 3: Property 2 — prove the Denys bite (IAM policy simulator; no resources created, ~free)**

```bash
DEPLOYER="arn:aws:iam::675789572470:role/annotated-maps-deployer"
BOUNDARY="arn:aws:iam::675789572470:policy/annotated-maps-boundary"
X="arn:aws:iam::675789572470:role/annotated-maps-x"

# (1) CreateRole WITHOUT boundary -> explicitDeny
aws iam simulate-principal-policy --policy-source-arn "$DEPLOYER" \
  --action-names iam:CreateRole --resource-arns "$X" \
  --query 'EvaluationResults[0].EvalDecision' --output text        # expect: explicitDeny

# (2) CreateRole WITH boundary -> allowed
aws iam simulate-principal-policy --policy-source-arn "$DEPLOYER" \
  --action-names iam:CreateRole --resource-arns "$X" \
  --context-entries "ContextKeyName=iam:PermissionsBoundary,ContextKeyType=string,ContextKeyValues=$BOUNDARY" \
  --query 'EvaluationResults[0].EvalDecision' --output text        # expect: allowed

# (3) AttachRolePolicy to a non-bounded role -> explicitDeny
aws iam simulate-principal-policy --policy-source-arn "$DEPLOYER" \
  --action-names iam:AttachRolePolicy --resource-arns "$X" \
  --query 'EvaluationResults[0].EvalDecision' --output text        # expect: explicitDeny

# (4) Rewrite the boundary policy -> explicitDeny (BoundaryPolicyImmutable)
aws iam simulate-principal-policy --policy-source-arn "$DEPLOYER" \
  --action-names iam:CreatePolicyVersion iam:SetDefaultPolicyVersion iam:DeletePolicy \
  --resource-arns "$BOUNDARY" \
  --query 'EvaluationResults[*].[EvalActionName,EvalDecision]' --output text   # expect: all explicitDeny

# (5) Delete a role's boundary -> explicitDeny
aws iam simulate-principal-policy --policy-source-arn "$DEPLOYER" \
  --action-names iam:DeleteRolePermissionsBoundary \
  --resource-arns "arn:aws:iam::675789572470:role/annotated-maps-node" \
  --query 'EvaluationResults[0].EvalDecision' --output text        # expect: explicitDeny

# (6) REGRESSION — the two scars must stay OPEN
aws iam simulate-principal-policy --policy-source-arn "$DEPLOYER" \
  --action-names iam:GetRole --resource-arns "$DEPLOYER" \
  --query 'EvaluationResults[0].EvalDecision' --output text        # expect: allowed
aws iam simulate-principal-policy --policy-source-arn "$DEPLOYER" \
  --action-names iam:CreateServiceLinkedRole \
  --resource-arns "arn:aws:iam::675789572470:role/aws-service-role/eks.amazonaws.com/AWSServiceRoleForAmazonEKS" \
  --query 'EvaluationResults[0].EvalDecision' --output text        # expect: allowed
```

All decisions must match. **Caveat:** if the simulator cannot model the `iam:PermissionsBoundary` condition key (cases 1/2/3 come back the same regardless of `--context-entries`), fall back to the live pipeline run in Step 5 as the authoritative proof of property 2, and record in the PR that the simulator was inconclusive on the condition key.

- [ ] **Step 4: Property 1 — prove the boundary does NOT break the cluster (live apply)**

```bash
cd "$(git rev-parse --show-toplevel)"
make demo-up      # full apply as operator; creates the 3 roles WITH the boundary
```

Then assert:

```bash
# Cluster up
aws eks describe-cluster --name annotated-maps-demo --query 'cluster.status' --output text   # ACTIVE
kubectl get nodes                                                                            # 2x Ready (node role works under cap)

# App reachable through the ALB (the ALB controller did real AWS work under the cap)
kubectl get ingress -A                                                                       # ADDRESS populated
ALB=$(kubectl get ingress -A -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}')
curl -fsS "http://$ALB/api/v1/health"                                                        # healthy

# All three roles carry the boundary
for r in $(aws iam list-roles --query "Roles[?contains(RoleName,'annotated-maps-demo-cluster')||contains(RoleName,'annotated-maps-node')||RoleName=='annotated-maps-alb-controller'].RoleName" --output text); do
  echo -n "$r -> "
  aws iam get-role --role-name "$r" --query 'Role.PermissionsBoundary.PermissionsBoundaryArn' --output text
done   # each -> arn:aws:iam::675789572470:policy/annotated-maps-boundary
```

**If apply or the ALB fails on a capped action** (e.g. a `AccessDenied` for the cluster/node role on something outside the six families, or a service-linked-role the cluster role needs that the boundary's SLR condition excludes): the boundary is too tight. Remedy = add the *precise* missing action (or the specific `iam:AWSServiceName` to `AlbControllerSlr`) to `boundary.tf` — never widen a resource scope — then re-run from Step 2. Record the addition in ADR-0012's honest-deltas list.

- [ ] **Step 5: (Strongest, optional) exercise the deployer principal end-to-end**

If David wants property 1 + property 2's positive path proven together as the *real* principal, trigger `demo-pipeline.yml` via `workflow_dispatch` (it federates in as the deployer via OIDC and runs `demo-up` as the deployer). A green run proves the deployer's own `CreateRole`-with-boundary succeeds (the Denys don't block legitimate creates) and the cluster comes up capped. This is heavier than Step 4; the simulator matrix + operator `demo-up` is the required gate, this is the belt-and-braces.

- [ ] **Step 6: Tear down and sweep**

```bash
make demo-down    # full destroy to zero (proves the unconditioned destroy path)
```

Then run the billable-resource sweep per repo protocol (the sweep at the end of `scripts/demo-down.sh`; confirm no EKS clusters, NAT gateways, or load balancers remain). **Nothing billable may be left running.**

- [ ] **Step 7: Merge**

With static CI green, the simulator matrix green, and the live apply/destroy clean, merge the PR. Then run the post-merge protocol: `git checkout main && git pull`, grep `main` for `annotated-maps-boundary` to confirm the change landed, move the #109 board card to **Done**, delete the branch (local + remote), and update the session ledger / `docs/lessons-learned.md` if this run surfaced anything (e.g. a boundary-too-tight widening from Step 4).

---

## Self-Review

**Spec coverage** (against the design spec §1–§9):
- §4 boundary policy → Task 1 (with the mechanically-derived ALB extras; refinement #1 corrects the spec's guessed list).
- §5 four Denys + interaction check → Task 2 (as five statements; refinement #2). Scar-safety asserted in Task 2 Step 4 and Task 5 Step 3 case 6.
- §6 demo wiring (3 roles + local + caller identity + foundation output) → Task 3 + Task 1 Step 3. All three attachment points covered; the spec's "these three are the complete set" is verified live in Task 5 Step 4.
- §7 ADR-0012 + ADR-0010 status + comment updates → Task 4 + Task 2 Step 2.
- §8 rollout ordering + live checkpoint + static-gates-insufficient → Task 5 (branch-verify-then-merge chosen over the spec's merge-first, so verification precedes merge; rollback noted).
- §3 "deployer not capped" → encoded in ADR-0012 and Task 3's scope (deployer untouched by wiring).
- §9 out-of-scope items (CI role, OIDC trust, SCPs) → not touched by any task. ✓

**Placeholder scan:** no TBD/TODO; every code step shows exact HCL; every command shows expected output. ✓

**Type/name consistency:** `aws_iam_policy.deployer_boundary.arn` (Task 1) is referenced identically in Task 2; `local.deployer_boundary_arn` (Task 3 Step 1) is used identically in Steps 2–4; policy name `annotated-maps-boundary` matches between `boundary.tf` (Task 1), the by-convention ARN (Task 3), and every simulator/`get-role` assertion (Task 5). ✓

**Deviations from spec (intentional, flagged for the ADR):** ALB-extras list (refinement #1), five-vs-four Deny statements (refinement #2), verification split by principal + simulator (refinement #3), branch-verify-then-merge ordering. All recorded in Global Constraints and ADR-0012.
