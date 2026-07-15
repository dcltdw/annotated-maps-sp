# ADR-0010: The demo pipeline's apply role — broad by necessity, AdministratorAccess-equivalent by consequence
- Status: accepted
- Date: 2026-07-15

## Context

Milestone 4's one-button pipeline (`demo-pipeline.yml`) needs a role that can
actually create and destroy the demo stack — VPC, EKS, ECR, the ALB
controller's resources, the Neon branch's supporting infra — unlike
`annotated-maps-ci` (ADR-0009), which is deliberately read-only plan. That
apply-capable role, `annotated-maps-deployer`
(`deploy/terraform/foundation/iam-deployer.tf`), is granted broad per-service
powers (`ec2:*`, `eks:*`, `ecr:*`, `elasticloadbalancing:*`, `autoscaling:*`,
`logs:*`) because `terraform apply` of this stack legitimately needs them —
narrowing those to individual actions would be false precision, since the EKS
module alone touches dozens of EC2/IAM/Auto Scaling calls across a single
`apply`. IAM itself is scoped to the `annotated-maps-*` resource prefix, S3 to
the one state bucket, SNS to the one alerts topic.

State that plainly, before anything else in this document: **within AWS
account `675789572470`, the `annotated-maps-deployer` role is
AdministratorAccess-EQUIVALENT.** The `annotated-maps-*` IAM prefix is a
blast-radius and typo guard — it stops a bug or a fat-fingered resource name
in the demo stack from touching an unrelated identity — it is **not** a
security boundary against a principal holding this role and acting
maliciously. A reader who spots that in thirty seconds and finds this ADR
silent about it would be right not to trust anything else in this milestone,
so the rest of this document is written on the assumption that claim has
already been read.

## Decision

**Accept the AdministratorAccess-equivalence, close what's cheap to close,
enumerate the rest, and ticket the real fix.** The alternative — a tight
permissions boundary before shipping the pipeline — was rejected for this
iteration only because the boundary is genuinely more design work than the
rest of the pipeline combined (see Consequences), and this milestone's
purpose is to prove the ephemeral-apply/destroy loop works end to end, not to
ship a hardened multi-tenant IAM model. The escalation paths below are
enumerated honestly rather than papered over with the prefix guard's name.

**Escalation paths, enumerated:**

- **Path A — CLOSED.** `iam:*` on `role/annotated-maps-*` matches the
  deployer's own ARN (`role/annotated-maps-deployer`), so without a specific
  denial the role could call `iam:AttachRolePolicy` to attach
  `AdministratorAccess` to itself in one API call. This is closed by an
  unconditional `NoSelfEscalation` Deny statement targeting exactly this
  role's ARN. A Deny always wins over an Allow in IAM policy evaluation, and
  the statement is self-protecting: the role cannot use `iam:PutRolePolicy`
  or any other `iam:*` call to remove the Deny from its own policy, because
  the Deny itself blocks that call.
- **Path B — OPEN, accepted.** `iam:CreateRole` (any name matching
  `annotated-maps-*`) → `iam:AttachRolePolicy AdministratorAccess` on that new
  role → `iam:CreateInstanceProfile` + `iam:AddRoleToInstanceProfile` →
  `iam:PassRole` on the new role + `ec2:RunInstances` with that instance
  profile → admin credentials readable off that instance's metadata service.
  Every action in that chain is inside the `annotated-maps-*` prefix and the
  `InfraServices` `ec2:*` grant, so none of it trips `NoSelfEscalation` — the
  Deny only matches the deployer's own literal ARN, and this chain never acts
  on that ARN. Critically, the admin credentials that come out the far end
  belong to a **different principal** (the new role, not
  `annotated-maps-deployer`), and that different principal is not subject to
  `NoSelfEscalation` at all — it can strip or rewrite any Deny it likes,
  including deleting `annotated-maps-deployer` outright. **The Deny therefore
  raises the cost of escalation — one API call becomes roughly four plus an
  EC2 instance boot — it does not close escalation.** Say that plainly rather
  than let the Deny read as a fix it isn't.
- The `iam:*` grant on `oidc-provider/oidc.eks.*` (added so the EKS module can
  create and, on `demo-down`, destroy the cluster's IRSA OIDC provider — see
  Consequences) also permits federating an attacker-chosen OIDC issuer host
  into a brand-new `annotated-maps-*`-prefixed role's trust policy. That sits
  entirely inside Path B's existing blast radius — Path B already yields
  account admin — so it does not open a new risk class, but it is listed here
  because a partial account of Path B that omits it would understate the
  `iam:*` grant's reach.

**Why this is accepted, not just disclosed:** the AWS account is dedicated to
this demo, holds no production data, and is disposable — there is nothing in
it an attacker with account-admin could ransom that isn't already
recreatable from this repository's Terraform. The only door into the account
is GitHub OIDC federation scoped to exactly one subject,
`repo:dcltdw/annotated-maps-sp:environment:aws-deploy` (see the trust policy
below), reachable only by triggering `demo-pipeline.yml`'s
`workflow_dispatch` or its `schedule`. Forks cannot trigger either — a
scheduled workflow only runs on the default branch of the repository that
owns it, and `workflow_dispatch` requires the caller to already have write
access to this repository. So anyone able to walk through that door is
already a maintainer with push access; nothing about IAM escalation grants a
class of access they didn't already have as a GitHub principal. It's also
worth being honest that `ec2:*` is granted outright for infrastructure
reasons, so **cost abuse needs no escalation path at all** — a compromised or
careless deployer run could `RunInstances` at will without ever touching IAM
— and the real control on that axis is the account's $10 AWS Budgets alarm
(`deploy/terraform/foundation/budgets.tf`), not an IAM boundary. What
escalation genuinely buys past that baseline is **guardrail removal and
persistence**: deleting the budget/SNS alarm, deleting the read-only
`annotated-maps-ci` role so `infra-plan` can no longer even observe the
account, or creating a role that trusts an external AWS account and so
survives revoking this repo's GitHub OIDC trust entirely.

**The real fix is a permissions boundary on `annotated-maps-*`-prefixed
principals**, which would cap what any role or policy created *by* the
deployer can itself be granted, closing Path B rather than merely taxing it.
That work is not done here — it is filed on the project board (Todo) as
follow-up, deliberately separated from this pipeline so the ephemeral
apply/destroy loop could be proven working first.

**Standing constraint — state this prominently, not as a footnote:** the
trust policy's OIDC `sub` condition,
`repo:dcltdw/annotated-maps-sp:environment:aws-deploy`, is **branch-agnostic**
— it is scoped to the GitHub Environment name, not to any ref or branch. That
is fork-safe *today* only because **every** workflow in this repository that
requests `permissions: id-token: write` while declaring
`environment: aws-deploy` is triggered exclusively by `workflow_dispatch` or
`schedule`. A future job that named `environment: aws-deploy` but triggered
on `pull_request_target` — even one added for an unrelated reason, months
from now — would hand a fork's pull request this AdministratorAccess-
equivalent role, no approval required, because the Environment is
deliberately unprotected (see below). That is precisely the class of bug
ADR-0009 documents catching during Milestone 3's review (`pull_request`
producing a base-repo-scoped OIDC subject a fork could still trigger) —
recorded here again because the fix that time was scoping to a protected
Environment, and this time the mitigation is a discipline about *which
trigger types* are allowed to name this particular Environment, which the
platform does not enforce for you. The `aws-deploy` Environment is
deliberately left **without** a deployment-branch policy or a required
reviewer for now — see the reviewer-gate discussion below for why — so this
constraint is a human invariant on the workflow files, not a GitHub setting,
until the deployment-branch policy work (also ticketed) lands after the live
iteration in this milestone is done and the pipeline no longer needs to be
dispatchable from a non-`main` branch.

**The reviewer gate is deliberately omitted**, and that omission is a
decision, not an oversight. `demo-pipeline.yml`'s only triggers are
`workflow_dispatch` and `schedule`; as established above, both are
fork-unreachable and `workflow_dispatch` already requires the invoking
principal to have write access to the repository. A required reviewer on the
`aws-deploy` Environment would therefore ask a maintainer to approve a run
that only a maintainer could have started — the same human confirming their
own action twice, not a second set of eyes. Worse, GitHub Environment
approval is granted **per job**, not per workflow run: a gate placed on any
job that can lead to `destroy` (directly, or via `needs`) can leave that job
sitting in a pending-approval state indefinitely if nobody happens to click
approve — and a `destroy` job stuck pending approval is exactly the stranded-
billing failure mode this whole milestone exists to prevent (an EKS control
plane plus two `t3.medium` nodes plus a NAT gateway, left running because a
human forgot to click a button). `workflow_dispatch` itself *is* the
confirmation step this pipeline relies on. If a reviewer gate is ever
reinstated, it must be an entry-only rule — attached to `provision`, never to
anything `destroy` depends on — so it cannot block teardown. This repo
already demonstrates the pattern where a required reviewer is the right
control: `infra-plan` (ADR-0009) puts the protected `aws-plan` Environment in
front of `terraform plan`, because that job runs on `pull_request`, which
*is* reachable by genuinely untrusted fork input, and a read-only plan is a
low-enough-stakes action to gate without risking a stuck destroy.

**SNS lifecycle events use one topic with a `severity` message attribute**
(`deploy/terraform/foundation/sns.tf`, ADR context from the M4 spec), not
three separate topics. `demo-ready`, `run-summary`, and `teardown-failed` all
publish to `annotated-maps-alerts`; the email subscription's filter policy
matches only `severity = "alert"`, so the inbox receives failures and nothing
else, while the topic itself carries the full lifecycle for anything that
later wants to consume it (a dashboard, a wider subscription). Message
volume is a handful of publishes per run, comfortably inside SNS's free tier
— effectively $0.

**No customer-managed KMS key for the EKS cluster's secrets envelope
encryption** (`create_kms_key = false` in `deploy/terraform/demo/eks.tf`).
The demo cluster holds no sensitive data — the application's actual secret,
the Neon connection string, never touches a Kubernetes Secret's envelope
encryption path in a way that needs a customer key beyond what AWS provides
by default for control-plane storage — and it lives for on the order of an
hour per run. A customer-managed key costs nothing to create, but
`terraform destroy` cannot delete a KMS key outright; it can only schedule
deletion, with a minimum seven-day pending-deletion window. On a stack
destroyed and recreated on a schedule, that is a new key accruing pending-
deletion charges (roughly $1/month each) that never fully clears — a slow
accumulating cost for a checkbox that buys nothing this workload needs.

**Neon connection strings are minted per run, not stored.** `deploy job`
calls `scripts/neon-branch.sh create ci-run-<run_id>` to open a fresh Neon
branch and writes its connection URI to a file consumed by `--set-file` (never
a command-line argument, never a workflow log). `destroy` deletes that same
branch by name. The only long-lived secret in this design is `NEON_API_KEY`,
a revocable Neon API key — not a database password. If it leaks, it is
rotated in the Neon console and every prior branch it created remains exactly
as compromised or as safe as it always was; a leaked static database
password, by contrast, would have compromised every environment sharing it
until manually rotated everywhere.

**The Trivy gate fails the build only on `CRITICAL` severity findings that
have a fix available** (`severity: CRITICAL`, `ignore-unfixed: true`,
`exit-code: "1"`). An upstream base-image CVE with no vendor fix yet would,
under a plain "fail on CRITICAL" gate, wedge the pipeline indefinitely with
no action the deployer could take to unstick it. `--ignore-unfixed` keeps the
gate meaningful — it still blocks anything actionable — without turning an
unpatched upstream advisory into a standing outage of the demo pipeline.
CycloneDX SBOMs are generated and uploaded as artifacts regardless of gate
outcome, so the software inventory is captured even on a failed (or blocked)
run.

## Consequences

- **The permissions boundary is the honest next step, not this ADR.** Until
  it lands, every fact stated above about Path B remains true on every run of
  this pipeline: `annotated-maps-deployer` can reach account-admin in roughly
  four API calls plus an instance boot, by a principal the `NoSelfEscalation`
  Deny does not and cannot reach. This ADR's job is to make sure nobody
  reading this repo has to discover that by reverse-engineering the policy
  document.
- **This design already caught one functional bug during review, in the
  exact failure mode this milestone exists to prevent.** `enable_irsa = true`
  in `deploy/terraform/demo/eks.tf` makes the EKS module create the cluster's
  IRSA OIDC provider, an ARN of the form
  `oidc-provider/oidc.eks.<region>.amazonaws.com/id/<hash>` that carries no
  `annotated-maps-*` prefix and so, before the fix, matched none of
  `IamWithinPrefix`'s resource ARNs. `terraform apply` would have failed to
  create it, and — the sharper problem — a subsequent `terraform destroy`
  would have failed to delete it, `AccessDenied` on both ends. A destroy that
  cannot complete is precisely the stranded-billing scenario the whole
  pipeline is built to prevent, so this was not a cosmetic gap: it would have
  turned the first live run into the thing this milestone exists to rule out.
  The fix scopes `IamWithinPrefix` to also allow
  `oidc-provider/oidc.eks.*` — narrower than the reviewer's suggested
  `oidc-provider/*`, and confirmed against the module source and a real
  `tfstate` not to match the foundation stack's GitHub OIDC provider
  (`oidc-provider/token.actions.githubusercontent.com`), so the deployer still
  cannot touch `annotated-maps-ci`'s trust anchor. That grant is also the
  source of the `oidc-provider/oidc.eks.*` escalation note under Path B above.
- Because `create_kms_key = false`, EKS secrets envelope encryption relies on
  AWS's default control-plane storage encryption rather than a customer-
  managed key — acceptable for this workload (see Decision), but it means
  this cluster does not demonstrate CMK-based envelope encryption as a
  pattern; a reader looking for that specific skill signal won't find it
  here.
- The reviewer-gate omission means a maintainer who triggers
  `workflow_dispatch` is, in effect, the sole check on that run — there is no
  second human in the loop before AWS resources are created. That is the
  intended trade-off (see Decision) but it means a compromised maintainer
  GitHub account with write access is sufficient to run this pipeline, same
  as it would be sufficient to push any other change to this repository.
- The `severity`-filtered SNS subscription means anything published with
  `severity=info` (the common case — `demo-ready`, `run-summary`) is
  invisible unless someone widens the filter policy or checks the topic
  directly; only `severity=alert` reaches the inbox by design.

## Alternatives considered

- **Reviewer-gated `workflow_dispatch`.** Rejected: as argued in Decision,
  the gate would ask the same human who triggered the run to re-approve
  themselves, and GitHub's per-job approval semantics mean a gate anywhere
  upstream of `destroy` risks leaving teardown pending indefinitely — the
  exact stranded-billing failure this milestone exists to prevent. `aws-plan`
  (ADR-0009) already shows where a reviewer gate belongs in this repo: in
  front of a job reachable by genuinely untrusted input (a fork's PR), not in
  front of a maintainer confirming their own dispatch.
- **Alerts-only SNS (no `demo-ready`/`run-summary` publishes).** Rejected:
  the marginal cost of also publishing the non-alert lifecycle events is
  effectively zero (still comfortably inside SNS's free tier), and having
  the full lifecycle on the topic — not just failures — means a future
  subscriber (a dashboard, a wider-filtered mailbox) doesn't require
  reworking the publish sites, only its own subscription's filter policy.
- **A persistent foundation-level KMS key**, created once and reused by every
  run instead of per-run key creation avoided entirely. Rejected: it would
  avoid the pending-deletion churn a per-run key would cause, but the
  cluster's actual need for customer-managed envelope encryption is zero for
  this workload (see Decision) — paying to maintain a persistent key for a
  property the demo doesn't need is worse than not having the property at
  all. `create_kms_key = false` is the honest reflection of "this workload
  doesn't need this," not a cost hack around a feature the workload wants.
- **A static, shared Neon database/password** provisioned once in the
  foundation stack instead of a Neon branch minted per run. Rejected: it
  reintroduces a long-lived database credential into CI secrets — exactly
  the class of credential ADR-0009 already avoids for AWS access via IRSA and
  OIDC — and it would mean every run's data lived in the same database,
  contaminating one run's fixtures/state with the next's rather than each
  run getting a clean, disposable branch that composes naturally with
  ephemeral infrastructure.
