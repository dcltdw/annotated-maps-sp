# ADR-0009: EKS over ECS (and Terraform over OpenTofu)
- Status: accepted
- Date: 2026-07-09

## Context

Milestone 1 produced the portable asset this repo is actually demonstrating:
a Helm chart, proven end-to-end on a local `kind` cluster. Milestone 3 has to
pick where that chart runs in AWS, and pick the tool that provisions it. Both
choices are judged against the same question — what does this repo exist to
show a reader? — not against "what's cheapest for one small app," which has
a different, honest answer.

## Decision

**Compute: Amazon EKS**, not ECS+Fargate. The chart's portability is the
thing Milestone 1 built and Milestone 3 exists to prove: `helm install` with
a different `values-demo.yaml` — image registry, ingress class/annotations,
`postgres.enabled: false` — is the entire diff between kind and a managed
AWS cluster. Landing on ECS would mean rewriting the deployable unit as task
definitions and services, discarding the chart as the artifact under test.
EKS also happens to be the market-relevant skill: "ran Kubernetes on AWS,
wired IRSA, wrote the Terraform" reads as a stronger signal than "ran
containers on Fargate," even though the latter is the better engineering
call for a single small app (see Alternatives).

**Provisioning: Terraform**, not OpenTofu. Terraform remains the tool
candidates and interviewers expect by default; that market recognition is
the whole reason to pick it here over its (functionally near-identical,
license-driven) fork. This wasn't a hypothetical trade-off — we hit the fork
story directly while setting up tooling for this milestone. Terraform's
August 2023 relicensing from MPL to the Business Source License is *why*
HashiCorp pulled `terraform` from `homebrew-core` and stood up its own
`hashicorp/tap` formula, and it's the same event that prompted `tflint` to be
removed from `homebrew-core` (a lint tool depending on a BSL-licensed
provider ecosystem was no longer a fit for the core tap). Both tools were
installed here from their own release artifacts instead of a plain `brew
install`. We chose Terraform anyway, friction and all, because the
resulting skill and file format are what a hiring manager will recognize.

**App pods hold no AWS IAM role.** The only pod in the cluster with an IRSA
role is the `aws-load-balancer-controller`, because it is the only pod that
genuinely needs to call the AWS API (creating/updating the ALB and its
target groups from Ingress objects). The application talks to its database
over TLS to Neon, not to S3 or any other AWS service, so it has nothing to
authenticate to AWS for. This is a *decision*, recorded here so it reads as
one: least privilege isn't "we forgot to grant the app pods a role," it's
"the app pods have no AWS-shaped need, so none exists to grant."

**CI's OIDC trust is push-to-main only.** The GitHub Actions role
(`annotated-maps-ci`, `deploy/terraform/demo/iam-ci.tf`) trusts exactly the
subject `repo:dcltdw/annotated-maps-sp:ref:refs/heads/main` — a push event on
this repo's own main branch — and nothing else. See Consequences for why
`pull_request` is deliberately excluded.

## Consequences

- The chart itself required almost no change to reach AWS: an ingress
  annotations passthrough and a values file. That's the intended payoff of
  Milestone 1's investment, made visible.
- Running EKS costs real money even at rest — a managed control plane, two
  `t3.medium` nodes, and a NAT gateway run roughly **$180/month if left
  always-on**. This repo never leaves it on: `make demo-up` / `make
  demo-down` bring the whole stack from zero to a working load-balanced app
  and back in one script each, and a single up → exercise → down cycle costs
  on the order of **$1–2**. Ephemeral-by-design is the only way EKS is
  affordable for a portfolio project, and it's why `demo-down` is written to
  be safe to re-run from any half-failed state rather than something to
  babysit.
- **Security note — why not `pull_request`:** on a public repository, a
  GitHub Actions OIDC job triggered by `pull_request` produces a token whose
  subject claim is scoped to the **base** repository, not the fork —
  including for pull requests opened *from* forks. A trust policy that
  accepted `repo:dcltdw/annotated-maps-sp:pull_request` would therefore be
  assumable by any fork's PR workflow, which is not a trust boundary anyone
  should ship on a public repo. Restricting the trust policy to
  `ref:refs/heads/main` means only a push that has already landed on main —
  something only a repo collaborator can produce — can assume the role. If
  plan-on-PR is ever wanted, the safe path is a **protected GitHub
  Environment**, whose OIDC subject takes the form
  `repo:OWNER/REPO:environment:NAME` and can be required to have reviewers;
  that is a deliberate future addition, not a relaxation of this trust
  policy to bare `pull_request`.
- Because IRSA and OIDC federation are both short-lived, token-based
  credentials, and the operator's laptop uses IAM Identity Center (SSO)
  rather than an IAM user's access keys, there are no long-lived AWS
  credentials anywhere in this system — not in CI secrets, not in a pod env
  var, not in a laptop's `~/.aws/credentials`.

## Alternatives considered

- **ECS + Fargate.** Genuinely the better engineering call for one small
  app: no cluster control-plane cost, no node group to size, no Kubernetes
  version to track, a smaller IAM surface. Rejected with respect — it would
  ship faster and cost less, but it answers a different question than the
  one this milestone is asking. It would also strand the Helm chart:
  Milestone 1's asset would have no role to play in Milestone 3 at all.
- **OpenTofu.** The open-source fork of Terraform post-BSL, and a completely
  reasonable default for a new project today. Rejected here specifically
  because market recognition — what a reader or interviewer already knows
  how to read — is the deciding factor for a portfolio repo, and Terraform
  still wins that comparison even after the license change and its Homebrew
  fallout (see Decision).
- **Spot instances for the node group.** Would shave marginal compute cost
  further, but this milestone expects several apply/destroy debug cycles
  before the one clean documented run; a spot reclaim mid-debug-cycle costs
  more in lost time than it saves in dollars at this scale. `ON_DEMAND`,
  noted in `deploy/terraform/demo/eks.tf`.
