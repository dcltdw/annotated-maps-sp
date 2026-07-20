<!-- doc-status: dated -->

# The deployer permissions boundary

- Date: 2026-07-20
- Prerequisite: [AWS IAM from zero](foundation-aws-iam.md). This walkthrough uses
  roles, ARNs, the Allow/Deny model, instance metadata, `PassRole`,
  service-linked roles, and permissions boundaries without re-explaining them.
- Describes: the design in
  [the #109 spec](../../superpowers/specs/2026-07-20-deployer-permissions-boundary-design.md),
  which closes the escalation disclosed in
  [ADR-0010](../../adr/0010-pipeline-apply-role.md). The spec is the authority on
  *what to build*; this is the guided tour of *what it means and why every piece
  is there.*

A note on tense: at the time of writing this is a **design under
implementation.** The walkthrough describes the intended end state. If you're
reading after it shipped, the story is history; if before, it's a map.

---

## 1. The setting, in one paragraph

This project runs an ephemeral AWS demo: a pipeline spins up a whole Kubernetes
cluster from nothing, runs the app on it for an hour or so, and tears it all back
down — cheaply, on a schedule, leaving nothing billable behind. To do that, the
pipeline assumes one role, **`annotated-maps-deployer`**, that is powerful enough
to create and destroy the entire stack. That power is the subject of this
document. The role is defined in
`deploy/terraform/foundation/iam-deployer.tf`, and if you read one source file
alongside this explainer, make it that one — its comments narrate the same story
from the code's side.

---

## 2. "AdministratorAccess-equivalent" — what that actually means

The spec opens by calling the deployer role
*"AdministratorAccess-equivalent within account 675789572470."* Unpacked:

The role's permission policy looks scoped. Its powers over IAM (creating roles,
attaching policies) are fenced to resources named `annotated-maps-*`. A first
read suggests "it can only touch its own project's stuff." **That fence is a
typo-guard, not a security wall** — and the distinction is the whole point.

- As a **typo-guard**, the `annotated-maps-*` prefix is doing real work: a bug or
  a fat-fingered resource name in the demo's infrastructure code physically
  cannot scribble on some unrelated identity elsewhere in the account. Good.
- As a **security wall against a malicious wearer**, it fails — because *the role
  can create brand-new identities inside that `annotated-maps-*` namespace*, and
  (from IAM primer §6) a newly created identity is a fresh principal that the
  original fence does not follow. The fence limits *which names* the role can
  create; it does nothing about the *power* those freshly named roles can be
  given.

So the honest description is: through a sequence of individually-legal moves, the
deployer can reach full administrator power over the whole account. In effect it
*is* an administrator, even though the word "AdministratorAccess" appears nowhere
in its policy. ADR-0010 states this bluntly on purpose — a reader who spotted it
and found the docs silent would rightly distrust everything else.

Why was such a powerful role acceptable at all? Because (IAM primer §11) the only
door to *becoming* the deployer is a GitHub OIDC workflow of an exact shape a fork
can't forge, and triggering it already requires repository write access. Anyone
who can exploit any of this is **already a maintainer** who could just push code.
The escalation grants no new class of access — with two exceptions we'll reach in
§5. That reasoning is why ADR-0010 *accepted and disclosed* the gap rather than
blocking the pipeline on fixing it. This design is the fix finally being built.

---

## 3. Two escalation paths: A (closed) and B (the target)

There are two ways to abuse the deployer's power. An earlier change (the PR known
in the history as "PR-D") closed the first. The second is what issue #109 and this
design are about.

### Path A — closed already

The blunt attack: the role attaches the AWS-managed `AdministratorAccess` policy
**to itself**. One API call. Because the role's IAM powers cover
`role/annotated-maps-*`, and the role's own name
(`annotated-maps-deployer`) matches that pattern, nothing stopped it.

The fix was an explicit **Deny** statement called **`NoSelfEscalation`**, scoped
to the deployer's own ARN. From IAM primer §4, a Deny always wins, so even though
a broad Allow covers IAM actions, this targeted "you may NOT modify *your own*
identity" overrides it. It's self-protecting, too: the role can't delete the Deny,
because deleting it is itself one of the denied actions.

One detail from that fix echoes through this whole design, so note it now:
`NoSelfEscalation` lists **specific mutating actions**, not a blanket `iam:*`.
The blanket version was tried first and **broke the very first live run** — the
cluster-creation tooling legitimately needs to *read* the deployer's own role
(`iam:GetRole`) while it figures out who's running the apply, and a blanket
`iam:*` Deny killed that read before a single resource was created. The lesson,
straight from IAM primer §4: *you cannot carve an Allow exception out of a Deny*,
so the Deny's action list itself has to be surgical — every action on it either
grants power or removes the Deny, and reads are left off because reads don't
escalate. Every new Deny in this design inherits that discipline.

The crucial *limitation* of `NoSelfEscalation`: it is scoped to the deployer's
**own** ARN. It only says "you can't escalate *yourself*." That is exactly the
gap Path B walks through.

### Path B — the open one, told as a story

Read this as five moves. Every single one is individually permitted by the
deployer's existing policy; the danger is only visible when you see where the
chain ends.

1. **Create a decoy role.** The deployer calls `iam:CreateRole` to make a new
   role — call it `annotated-maps-x` — whose *trust policy* says "an EC2 instance
   may wear me." Perfectly legal: the name is inside the `annotated-maps-*` fence.
2. **Make the decoy an admin.** It calls `iam:AttachRolePolicy` to attach
   `AdministratorAccess` **to that new role.** Legal — `NoSelfEscalation` guards
   only the deployer's *own* ARN, and `annotated-maps-x` is a *different* role, so
   the Deny doesn't fire. We now have a full-admin role sitting in the account.
3. **Wrap it for a machine.** `iam:CreateInstanceProfile` +
   `iam:AddRoleToInstanceProfile` package the admin role in an instance profile
   (IAM primer §7), the adapter that lets an EC2 instance wear it.
4. **Launch a machine wearing it.** `iam:PassRole` (the §8 guard) plus
   `ec2:RunInstances` boot an EC2 instance carrying that admin instance profile.
   The deployer's policy grants `ec2:*` outright, so this is unremarkable.
5. **Read the admin credentials out.** The running instance asks its metadata
   service (`169.254.169.254`) for its own credentials and gets back **live
   administrator credentials**, which the attacker now holds as an ordinary
   string usable from anywhere.

```
CreateRole annotated-maps-x (trusts ec2)
  → AttachRolePolicy AdministratorAccess   (onto the NEW role — NoSelfEscalation
                                             doesn't cover it)
  → CreateInstanceProfile + AddRoleToInstanceProfile
  → PassRole + ec2:RunInstances
  → read admin creds off 169.254.169.254
  ⇒ ADMINISTRATOR — as annotated-maps-x, a DIFFERENT principal
```

**The punchline is the last line.** The credentials belong to `annotated-maps-x`,
*not* to `annotated-maps-deployer`. `NoSelfEscalation` guards only the deployer.
This new admin principal is guarded by nothing — so it can turn around and **delete
`NoSelfEscalation` itself**, or do anything else in the account. The guardrail is
now *behind* the attacker.

Compared to Path A, Path B costs more — roughly four calls and an instance boot
instead of one call — but it lands in the identical place: full account admin, with
the one guardrail neutralized. Raising the cost is *all* `NoSelfEscalation` bought;
it did not close escalation, and ADR-0010 says so in plain words rather than
letting the Deny read as a fix it isn't.

---

## 4. Why anyone shipped with Path B open

Because the *marginal* danger is smaller than "full admin" sounds, once you
account for who can reach the door at all (§2). Spelled out in the spec and
ADR-0010:

- **Getting cost-abusive doesn't even need Path B.** The deployer already holds
  `ec2:*`, so a compromised or careless run could launch expensive instances
  without touching IAM at all. The real control on *that* axis was never IAM — it's
  the account's **$10 AWS Budgets alarm**. Escalation adds nothing here.
- **What escalation genuinely buys, beyond already being a maintainer, is two
  things:**
  - **Guardrail removal.** Full admin can *delete the budget alarm and its SNS
    notifications* — the only thing watching for runaway spend. Note the shape:
    escalation doesn't enable the cost abuse, it blinds the *detector* of it.
  - **Persistence.** Full admin can create a role that trusts an **external AWS
    account** the attacker controls. Now revoking this repo's GitHub OIDC
    trust — slamming the only known door (IAM primer §11) — *doesn't evict them.*
    They kept a side door in their own account. This is the genuinely alarming
    one, because it survives the obvious remediation.

(One thing that is *not* on the list, lest the design overclaim: the deployer can
already delete the read-only CI role **directly**, no escalation required, because
that role's name is inside the `annotated-maps-*` fence like everything else. That
was never Path B.)

So the target the boundary must actually hit: **stop a deployer-created principal
from ever exceeding the demo's ordinary powers — so it can't remove guardrails and
can't mint full-power external persistence — without breaking the legitimate roles
the demo genuinely creates.**

---

## 5. The fix in one idea

Every step of Path B rested on one move: **the deployer creating a role more
powerful than the deployer's own fence, then laundering into it.** A permissions
boundary (IAM primer §10) is precisely the tool that forbids that move.

The plan has two halves:

1. **Force the boundary onto everything the deployer creates.** Deny the
   deployer's role-creating and role-empowering actions *unless* the affected role
   carries a specific boundary policy (the `StringNotEquals`/absent-key mechanism
   from IAM primer §5). After this, the deployer literally cannot mint an uncapped
   role.
2. **Make the boundary a smart ceiling.** Write the boundary's Allow-set high
   enough that the three roles the demo legitimately creates still work, but low
   enough that laundering into a capped role buys an attacker nothing —
   specifically, no IAM, no SNS, no budgets, no state access.

With both halves in place, replay Path B: step 1 now produces a role *capped by
the boundary*; step 2 attaches `AdministratorAccess` but the boundary ceiling
means the role's *effective* power is still just "ordinary demo services" — no
`iam:*`, so it can't strip Denys; no `budgets:*`/`sns:*`, so it can't blind the
detector; no ability to grant itself anything the boundary doesn't already allow.
The chain dead-ends at step 2.

**Why this is a whole design and not a one-line Deny:** the boundary is a ceiling
on *real, working roles*. Set it too tight and the live cluster breaks — and it
breaks *invisibly*, because every static check (`terraform validate`, linting, the
plan-only CI job) passes on a boundary that will fail at apply time against the
real AWS API. Set it too loose and it stops capping anything and Path B reopens.
The rest of this document is that needle being threaded.

---

## 6. The boundary policy — writing a ceiling that doesn't break the cluster

The boundary is a new IAM policy, **`annotated-maps-boundary`**, defined in a new
file `deploy/terraform/foundation/boundary.tf`. It is created by the *foundation*
stack — the persistent, operator-applied layer — not by the deployer itself
(more on that split in §8).

The demo legitimately creates exactly **three** roles, and the boundary is the
ceiling on all three:

1. the **EKS cluster role** (the Kubernetes control plane's own identity),
2. the **EKS node role** (worn by the worker VMs), and
3. the **ALB-controller role** (worn by the one in-cluster component that talks to
   AWS, to manage load balancers).

The design's chosen approach for the Allow-set is a **service-level mirror**, and
it's worth understanding *why that shape* by contrast with the two alternatives
that were rejected (spec §3):

- **Rejected — an exact copy of the three roles' real policies.** Tightest
  possible ceiling, but AWS *updates its managed policies server-side* over time
  (the EKS worker policy today isn't byte-identical to a year ago). A frozen copy
  of them silently rots, and the failure mode is the worst kind: a mid-apply or
  mid-*destroy* `AccessDenied` on a live run — the stranded-billing scenario this
  whole pipeline exists to prevent.
- **Rejected — allow everything *except* a denylist of sensitive services.**
  Break-proof for the cluster, but the ceiling would then span every AWS service
  there is (Lambda, DynamoDB, everything) — a weak, loose boundary in a project
  whose whole point is demonstrating IAM rigor.
- **Chosen — mirror the deployer's own service surface.** The boundary allows the
  *same broad service families the deployer itself already holds*:
  `ec2:*`, `eks:*`, `ecr:*`, `elasticloadbalancing:*`, `logs:*`, `autoscaling:*`,
  plus two read-only KMS actions.

The security argument for the mirror is the clean part: **a capped role can never
exceed the service surface the deployer already had**, so laundering into a
created role gains an attacker *nothing they didn't already possess as the
deployer.* The escalation delta collapses to zero. The operational argument is
just as important: because the ceiling is drawn at the *service* level
(`ec2:*`, not a hand-picked list of EC2 actions), a version bump to the EKS module
or a newer node AMI that needs some additional EC2/EKS action *within those
families* is already allowed — the cluster doesn't break on the next upgrade.

### The one wrinkle: the ALB controller needs a few things the deployer doesn't

The load-balancer controller, at runtime, calls a handful of actions outside those
six service families — certificate lookups (`acm:...`), a Cognito read, and some
WAF/Shield associate-and-read calls. Those come from its **vendored policy**,
`deploy/terraform/demo/policies/alb-controller-iam-policy.json` (pinned at
controller version 2.17.1). If the boundary omitted them, the boundary's ceiling
would sit *below* what the ALB role legitimately needs, and the load balancer
would break.

So the boundary adds a second statement, **`AlbControllerExtras`**, containing
*exactly* those out-of-family actions and no more. The spec is deliberate that the
implementer should **re-derive this list mechanically from the vendored JSON** at
build time rather than trust any hand-typed list (including the one in the spec) —
parse the file, drop every action already covered by the six service families,
and allow what remains verbatim. It also adds **`AlbControllerSlr`**: permission to
create the load-balancing *service-linked role* (IAM primer §9), carrying the same
condition the vendored policy uses. That `CreateServiceLinkedRole` is the *only*
`iam:` action anywhere in the boundary.

### What the boundary does NOT allow — the actual security property

Everything not listed is capped out. In particular the boundary allows **no other
`iam:` actions** — including no `iam:PassRole`, so a capped role can't even chain
onward to yet another principal — and no `sns:`, no `budgets:`, no `s3:` (the
Terraform state bucket is unreachable), no `ce:`, no `organizations:`. That
omission list *is* the fix: it's precisely the "guardrail removal + persistence"
delta from §4, denied by simply never appearing in the ceiling.

### Honesty note (kept in the design on purpose)

The mirror isn't a perfect mirror, and the spec refuses to pretend otherwise. The
boundary allows the `acm`/`wafv2`/`shield`/`cognito-idp` actions the deployer
*doesn't* itself hold (the ALB role needs them) — a small, enumerated, mostly
read/associate surface. And it *omits* two actions the deployer does hold
(`sts:GetCallerIdentity`, `ce:GetCostAndUsage`) because created roles don't need
them. Stating these deltas out loud is the difference between a boundary you can
trust and one that merely sounds tidy.

---

## 7. Forcing the boundary on — the four new Deny statements

Section 6 built the ceiling. This section installs the rule that *nothing the
deployer creates can escape it.* Four new Deny statements are added to the
deployer's own policy in `iam-deployer.tf`. Remember the discipline from §3: each
Deny lists precise actions, never a blanket `iam:*`, so it can't re-break the
`iam:GetRole` read the cluster tooling needs.

1. **`DenyRoleCreateWithoutBoundary`** — Deny `iam:CreateRole` *unless* the
   creation request sets the permissions boundary equal to
   `annotated-maps-boundary`'s ARN. This is the `StringNotEquals`/absent-key
   trick (IAM primer §5): a `CreateRole` that omits the boundary trips the
   condition and is denied. Path B's step 1 now *cannot* produce an uncapped
   role — it either carries the boundary or fails.
2. **`DenyGrantWithoutBoundary`** — Deny `iam:AttachRolePolicy` and
   `iam:PutRolePolicy` unless the *target role* already carries the boundary. This
   guards the "empower a role" verbs directly, so even granting power to some role
   that slipped through is denied unless that role is capped. (The demo's own
   legitimate grants all target the three boundary-carrying roles, so they still
   work.)
3. **`DenyBoundaryTamper`** — Deny `iam:DeleteRolePermissionsBoundary` outright,
   and Deny `iam:PutRolePermissionsBoundary` unless it's setting the boundary *to*
   the canonical ARN. Without this, an attacker could simply *remove* a role's
   boundary after creating it, or swap it for a weaker one — undoing the whole
   scheme. (This permits the one legitimate case: Terraform setting the boundary
   to the *correct* ARN on a role that didn't get it at creation time.)
4. **`BoundaryPolicyImmutable`** — Deny the actions that would edit the boundary
   policy's *contents* (`iam:CreatePolicyVersion`, `iam:DeletePolicyVersion`,
   `iam:SetDefaultPolicyVersion`, `iam:DeletePolicy`) on the boundary policy's own
   ARN. **This one is subtle and easy to miss** — and it was caught during design.
   The boundary policy is named `annotated-maps-boundary`, which is *inside the
   `annotated-maps-*` fence the deployer can already edit.* Without this Deny, the
   deployer could just rewrite the boundary's contents to "allow everything" — a
   one-call bypass of the entire design. Naming the boundary inside the prefix
   opened the hole; this Deny closes it.

### The interaction check — not re-breaking the two scars

The design explicitly verifies the new Denys don't reopen either historical
failure recorded in `iam-deployer.tf`:

- **The `aws_iam_session_context` scar** (the `iam:GetRole`-on-self read that a
  blanket `iam:*` Deny killed): none of the four new Denys mention any *read*
  action, so the healed read stays healed.
- **The service-linked-role scar** (`iam:CreateServiceLinkedRole` +
  `iam:GetRole` on the `aws-service-role/` path): `DenyRoleCreateWithoutBoundary`
  targets `iam:CreateRole`, which — IAM primer §9 — is a *different action* from
  `iam:CreateServiceLinkedRole`, so SLR creation is untouched.

There's also a deliberate non-overlap: `NoSelfEscalation` already forbids
boundary tampering **on the deployer's own ARN**; `DenyBoundaryTamper` covers
*every other* role. The two together leave no role's boundary editable. And the
whole destroy path (`DeleteRole`, `DetachRolePolicy`, deleting instance profiles,
…) is left **unconditioned** on purpose — a role that somehow exists *without* a
boundary must still be destroyable, or teardown wedges and we recreate the exact
stranded-billing failure the pipeline exists to prevent.

---

## 8. Wiring two stacks together — and why the deployer isn't itself capped

Two structural decisions round out the design.

**The boundary lives in `foundation/`, but `demo/` needs its ARN.** The
infrastructure is split into two Terraform stacks: a persistent `foundation/`
layer (the state bucket, the roles, now the boundary policy) applied *locally by
an operator with real credentials*, and an ephemeral `demo/` layer (the cluster)
applied *by the deployer role in the pipeline*. The three roles that need the
boundary attached are created in `demo/`. How does `demo/` learn the boundary's
ARN?

The design's answer is **ARN by convention**: `demo/` constructs the ARN as a
string from the account ID and the known policy name. The tempting alternative —
have `demo/` *read* `foundation/`'s outputs via `terraform_remote_state` — is
actually impossible here, because `foundation`'s state is a *local* file on the
operator's machine, which the pipeline can't read. A live API *lookup* of the
policy would work but would require granting the deployer a new `iam:GetPolicy`
permission for no real benefit, since a permissions boundary is *just an ARN
string* — there's nothing to look up that convention doesn't already give you.
So the policy's *name* becomes a small, deliberate cross-stack contract, and
`foundation/` also exports it as an output purely to document that contract on
the producing side. The three attachment points are one line each on the cluster
role, the node group, and the ALB role.

**Does the deployer role get the boundary too? No — deliberately.** It's a fair
question: if boundaries are so containing, cap everything. But the deployer is
created by the `foundation` stack with *operator* credentials, and capping *it*
would force the boundary's Allow-set to also include all the IAM/state-bucket/SNS
powers the deployer legitimately needs — which would defeat the whole point of a
*tight* boundary. This is the standard AWS delegation pattern: **the control isn't
a ceiling on the powerful delegator, it's the delegator being forced to cap
everything it delegates.** The deployer's own limits remain its identity policy
plus `NoSelfEscalation`, and — crucially — only operator credentials can ever
mutate the deployer, so it can't quietly widen itself in a pipeline run anyway.

---

## 9. Why you can't trust a green CI run here

This deserves its own section because it's the most counterintuitive part.

Everything static passes on a boundary that would break the live cluster.
`terraform validate` checks syntax. `tflint` checks style and obvious
misconfigurations. The `infra-plan` CI job runs `terraform plan`, which computes a
*diff* — it never calls the real IAM evaluation engine against a real apply. **A
boundary whose ceiling is one action too low sails through every one of them and
then fails at 3am mid-apply**, when the EKS module tries to do something the
boundary forgot to allow — or, worse, fails mid-*destroy*, stranding a running
cluster nobody is paying attention to.

Therefore the design's final gate is **not** a CI check. It's a **live
apply/destroy cycle against the real AWS account, run as a checkpoint with the
maintainer** — roughly \$1–2 and half an hour, and *never left running.* The
checkpoint proves the things static analysis structurally cannot:

1. `make demo-up` — a full apply. This exercises `CreateRole` ×3 *under the new
   Deny* (the positive path: creation *with* the boundary must succeed), the
   managed-policy attaches onto capped roles, the `PutRolePolicy` on the capped
   ALB role, and both healed scars.
2. Runtime proof the ceiling isn't too low: cluster reports Active, both worker
   nodes reach Ready (the node role genuinely works *under the cap*), and the app
   is reachable through the load balancer (the ALB controller did real
   AWS work *under the cap*).
3. `aws iam get-role` on all three roles, confirming each shows
   `PermissionsBoundary = annotated-maps-boundary`.
4. `make demo-down` — a full destroy to zero, proving the unconditioned destroy
   path (§7) really does tear everything down, followed by the billable-resource
   sweep.

An optional extra: from a deployer shell, try `create-role` *without* the boundary
and watch it get `AccessDenied` — a direct demonstration that the cage bites. It's
a nice-to-have; the required evidence is the positive apply plus a clean destroy.

The ordering also matters and the design pins it: the code merges (which changes
*no* live IAM, since `foundation` is operator-applied), *then* the operator applies
`foundation/` locally to install the boundary and Denys, and because the merged
`demo/` code already carries the wiring, there's never a window where an old demo
tries to create a role the new Deny would reject. Rollback is symmetric and
instant: revert the local `foundation` apply.

---

## 10. What's closed, and what's honestly left

**Closed by this design:** Path B proper. A deployer-created role can no longer
exceed the demo's ordinary service surface, so it cannot remove the budget/SNS
guardrail, cannot strip any Deny (no `iam:` power under the cap), and cannot grant
itself anything the boundary doesn't already permit. The one-call boundary-rewrite
bypass (via the in-prefix policy name) is closed by `BoundaryPolicyImmutable`.

**Honestly residual** (and slated for ADR-0012 rather than swept under the rug):

- A capped role trusting an *external* account can still be *created* — but it is
  capped to the demo-service surface. It can't touch IAM, SNS, budgets, or state,
  and the budget alarm (which no deployer-created principal can now delete) remains
  the detector. Persistence is *possible* but *declawed*.
- **Cost abuse still needs no escalation at all** — `ec2:*` is granted to the
  deployer outright, exactly as before. The \$10 budget alarm remains the real
  control on that axis; this design never claimed to change it.
- The deployer can still delete the read-only CI role *directly* — that was never
  Path B (§4), and the design doesn't pretend it closes it.
- The boundary's small `acm`/`wafv2`/`shield`/`cognito-idp` surplus over the
  deployer's own powers (§6) is a real, enumerated widening, disclosed rather than
  hidden.

The documentation follow-through mirrors the code: a new **ADR-0012** records the
boundary decision and the residuals above, and **ADR-0010** — which is a *dated*
document that, per the repo's documentation-accuracy practice, is never rewritten
to match new code — gets exactly one change: its Status line points forward to
ADR-0012. The old disclosure of Path B stays intact as the historical record it
is; the new ADR carries the current truth. That's the same
"don't-falsify-the-past" discipline the boundary design applies to code, applied
to the docs.

---

## Where to go next

- The build instructions this narrates:
  [the #109 design spec](../../superpowers/specs/2026-07-20-deployer-permissions-boundary-design.md).
- The disclosure this supersedes:
  [ADR-0010](../../adr/0010-pipeline-apply-role.md).
- The role itself, whose comments tell the same story from the code side:
  `deploy/terraform/foundation/iam-deployer.tf`.
- The concepts, if any term here was a stretch:
  [AWS IAM from zero](foundation-aws-iam.md).
