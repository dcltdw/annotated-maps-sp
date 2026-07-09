# AWS & Terraform primer (this repo)

Companion to the [Kubernetes & Helm primer](kubernetes-primer.md): that
document explains the chart this repo ships; this one explains where
Milestone 3 runs it — real AWS infrastructure, defined entirely in Terraform,
spun up on demand and torn down to zero.

## 1. The mental model

Everything here nests inside one AWS account. Inside the account is one VPC
(`deploy/terraform/demo/network.tf`), spread across two availability zones
for the resources that need redundancy (the EKS control plane) even though
this demo doesn't pay for AZ-redundant *egress* — see the NAT note below.
Each AZ has a public subnet (where the load balancer lives, so it can have a
public IP) and a private subnet (where the EKS worker nodes live, so they
never have one). Inside the VPC is the EKS cluster; inside the cluster is
this repo's Helm chart, unchanged from the version that runs on `kind` —
only `values-demo.yaml` differs.

```
AWS account
└── VPC  10.0.0.0/16  (2 AZs)
    ├── public subnets   ── the ALB lands here (internet-facing)
    │        │
    │      one NAT gateway (shared across both AZs — cost decision,
    │        │               not a fault-tolerance one; see network.tf)
    │        ▼
    └── private subnets  ── EKS worker nodes (2x t3.medium)
             └── EKS cluster
                 └── this repo's Helm chart (same chart as kind)
```

The other half of the mental model is *how anything authenticates to AWS at
all* — and the answer, everywhere in this stack, is "not with a long-lived
access key." Three identities, three different short-lived mechanisms:

```
 laptop (you)  ──SSO──▶  IAM Identity Center  ──▶  short-lived console/CLI creds
 CI (GitHub Actions) ──OIDC──▶  annotated-maps-ci role   (Environment-gated plan-on-PR)
 pods (in-cluster) ──IRSA──▶  annotated-maps-alb-controller role  (one pod, one role)
```

- **Laptop → IAM Identity Center (SSO).** `aws configure sso` +
  `aws sso login` issue temporary credentials to your shell; nothing durable
  sits in `~/.aws/credentials`.
- **CI → GitHub OIDC federation.** GitHub Actions requests a short-lived
  token from GitHub's own OIDC provider and exchanges it for AWS credentials
  via `sts:AssumeRoleWithWebIdentity` — no AWS secret ever lives in GitHub.
  The trust policy (`foundation/iam-ci.tf`) only accepts that token for a job
  that declares the protected `aws-plan` GitHub Environment, which requires a
  human reviewer before the token is issued — see
  [ADR-0009](adr/0009-eks-over-ecs.md) for why bare `pull_request` is
  deliberately excluded.
- **Pods → IRSA (IAM Roles for Service Accounts).** EKS's OIDC provider lets
  a specific Kubernetes ServiceAccount assume a specific IAM role. Exactly
  one ServiceAccount in this cluster has a role at all: the
  `aws-load-balancer-controller`'s. The application pods have none — they
  talk to Neon over TLS, not to any AWS service — which is a decision, not
  an oversight ([ADR-0009](adr/0009-eks-over-ecs.md)).

No long-lived AWS keys exist anywhere in this system.

## 2. What each Terraform file does

```
deploy/terraform/
├── foundation/                persistent — applied once, never destroyed
│   ├── state.tf               S3 state bucket (+ versioning, encryption)
│   ├── iam-ci.tf              GitHub OIDC provider + CI role
│   ├── budgets.tf             cost guardrail
│   ├── outputs.tf             state_bucket, ci_role_arn
│   ├── providers.tf           AWS provider + default tags
│   ├── variables.tf           region / alert email
│   └── versions.tf            Terraform + provider version pins
└── demo/                      ephemeral — up/down every run
    ├── network.tf             VPC + subnets + NAT
    ├── eks.tf                 EKS cluster + node group
    ├── ecr.tf                 image repos
    ├── iam-irsa.tf            ALB-controller IRSA role
    ├── outputs.tf             values the scripts consume
    ├── backend.tf             where state lives
    ├── providers.tf           AWS provider + default tags
    ├── variables.tf           region / cluster name
    ├── versions.tf            Terraform + provider version pins
    └── policies/
        └── alb-controller-iam-policy.json   vendored controller IAM policy
```

| File | What it does |
|---|---|
| [`foundation/state.tf`](../deploy/terraform/foundation/state.tf) | Creates the S3 bucket that holds `demo/`'s remote state — applied once, with *local* state (the bucket can't store the state that creates it), gitignored. |
| [`foundation/iam-ci.tf`](../deploy/terraform/foundation/iam-ci.tf) | Hand-written: the GitHub OIDC provider and the `annotated-maps-ci` role — read-only `plan` permissions, trust restricted to a job running under the protected `aws-plan` GitHub Environment (see §1 and [ADR-0009](adr/0009-eks-over-ecs.md)). |
| [`foundation/budgets.tf`](../deploy/terraform/foundation/budgets.tf) | A $10/month AWS Budget with actual alerts at 50/80/100% and a forecast alert, emailed to the account owner — applied before any EKS spend exists, and never torn down, so the guardrail always covers the account. |
| [`foundation/outputs.tf`](../deploy/terraform/foundation/outputs.tf) | The state bucket name and the CI role ARN — the latter is what `demo/backend.tf` and CI's `terraform plan` job consume. |
| [`foundation/providers.tf`](../deploy/terraform/foundation/providers.tf), [`foundation/variables.tf`](../deploy/terraform/foundation/variables.tf), [`foundation/versions.tf`](../deploy/terraform/foundation/versions.tf) | Provider config + default tags, input variables (region, budget alert email — no default, never committed), and version pins. Plumbing, not exhibits. |
| [`demo/network.tf`](../deploy/terraform/demo/network.tf) | Community VPC module: 2 AZs, public + private subnets, **one** shared NAT gateway (not one per AZ) — an ephemeral demo doesn't need AZ-fault-tolerant egress, and a second NAT is another ~$0.045/hr for redundancy nobody's paying to keep up. |
| [`demo/eks.tf`](../deploy/terraform/demo/eks.tf) | Community EKS module: the cluster, a public API endpoint (no bastion for a throwaway demo), IRSA/OIDC enabled, one managed node group of 2× `t3.medium` on-demand (spot rejected — reclaims mid-debug-cycle cost more than they save at this scale). |
| [`demo/ecr.tf`](../deploy/terraform/demo/ecr.tf) | Two image repos (`annotated-maps-api`, `annotated-maps-web`), scan-on-push, `force_delete = true` so a repo still holding images never blocks `terraform destroy`. |
| [`demo/iam-irsa.tf`](../deploy/terraform/demo/iam-irsa.tf) | Hand-written: the `annotated-maps-alb-controller` role, trust-bound to exactly one ServiceAccount in this cluster, holding the vendored [ALB-controller policy](../deploy/terraform/demo/policies/alb-controller-iam-policy.json). This role stays in `demo/`, not `foundation/`, because it's bound to the per-demo cluster's own OIDC provider — it can't outlive the cluster it's tied to. |
| [`demo/outputs.tf`](../deploy/terraform/demo/outputs.tf) | Cluster name, region, VPC id, ECR URLs, and the ALB-controller role ARN — everything `demo-up.sh`/`demo-down.sh` read via `terraform output`. |
| [`demo/backend.tf`](../deploy/terraform/demo/backend.tf) | Points `demo/` at the S3 bucket `foundation/` created, using Terraform ≥1.10's native S3 lockfile (no DynamoDB lock table). Inert under `init -backend=false`, which is what static CI runs. |
| [`demo/providers.tf`](../deploy/terraform/demo/providers.tf), [`demo/variables.tf`](../deploy/terraform/demo/variables.tf), [`demo/versions.tf`](../deploy/terraform/demo/versions.tf) | Provider config + default tags, input variables (region, cluster name), and version pins. Plumbing, not exhibits. |
| [`demo/policies/alb-controller-iam-policy.json`](../deploy/terraform/demo/policies/) | The AWS Load Balancer Controller's own published IAM policy, vendored at a pinned version (v2.17.1) rather than fetched at apply time — pinned, reviewable, diffable. |
| [`scripts/demo-up.sh`](../scripts/demo-up.sh) | `terraform apply` → kubeconfig → install the ALB controller (IRSA-annotated) → build/push amd64 images to ECR → `helm upgrade --install` the app → poll for the ALB hostname → smoke-test it. |
| [`scripts/demo-down.sh`](../scripts/demo-down.sh) | Uninstall the app (so the controller deletes its ALB) → **wait for the ALB to actually be gone** → uninstall the controller → `terraform destroy` → a post-destroy sweep confirming zero. Safe to re-run from any half-failed state. |
| [`scripts/demo-cost.sh`](../scripts/demo-cost.sh) | Month-to-date AWS spend by service, via Cost Explorer — the per-cycle cost report. |

> **Lifetime split.** The GitHub OIDC provider, the CI role, and the budget
> alarm must actually *outlive* a demo: the budget alarm should always guard
> the account, and the CI role must exist for a PR's `terraform plan` even
> when no demo is up. They live in the **persistent `foundation/` stack**
> (applied once, never destroyed), while `demo/` holds pure ephemeral compute
> (VPC/EKS/ECR + the cluster-bound IRSA role, which can't move to
> `foundation/` because it's tied to the per-demo cluster's own OIDC
> provider). Split by lifetime, not by layer.

## 3. Commands

    make demo-up      # terraform apply + ALB controller + image push + deploy — ~$0.20/hr while up
    make demo-cost     # month-to-date spend by service, printed as a table
    make demo-down     # tear everything back to zero — safe to re-run from any state

- `demo-up` leaves the meter running at roughly **$0.20/hr** (EKS control
  plane + 2 nodes + one NAT gateway). A full up → exercise → down cycle costs
  on the order of **$1–2**; leaving it running for a month would run
  **~$180** ([ADR-0009](adr/0009-eks-over-ecs.md)).
- **The rule: never leave it up.** There is no "just for tonight." Every
  session that brings the demo up ends that same session with `make
  demo-down`, unconditionally — including, especially, when something failed
  partway through.

## 4. Live-run protocol (runbook)

1. **Budgets before anything else.** `budgets.tf` gets applied first (before
   EKS exists), and the alert email is confirmed to arrive before any
   spend-generating resource is created. The guardrail exists before there's
   anything to guard against.
2. **One cost check per cycle.** After every `demo-up` → exercise →
   `demo-down` cycle, run `make demo-cost` and record the number. This is
   the receipt, not a formality — it's how "back to zero" gets verified
   instead of asserted.
3. **$15 hard ceiling.** If cumulative month-to-date spend approaches $15,
   stop and regroup rather than continuing to iterate. This is well above
   what a clean handful of debug cycles should cost; hitting it means
   something is wrong (see Troubleshooting) or is being left running
   between sessions.
4. **`demo-down` runs on any failure, no exceptions.** A failed `demo-up` —
   a bad apply, a stuck rollout, a broken smoke test — is torn down before
   doing anything else, including before debugging. Debug the *next*
   `demo-up`, not a lingering half-up cluster.

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `terraform destroy` hangs deleting the VPC / subnets | An orphaned ALB (created out-of-band by the in-cluster controller, not by Terraform) is still attached to those subnets | Re-run `make demo-down` — it waits for the controller to delete the ALB before touching Terraform. If it's still stuck, delete the load balancer and its target groups by hand in the EC2 console, then re-run `demo-down`. |
| A just-created IAM role fails `AssumeRole` for the first ~10s | IAM changes propagate asynchronously across AWS; the role isn't visible everywhere yet | Wait ~10 seconds and retry. Not a bug — expected IAM propagation delay. |
| `docker push` to ECR suddenly fails with an auth error | ECR login tokens expire after 12 hours | Re-run the `aws ecr get-login-password \| docker login ...` line from `demo-up.sh` and retry. |
| Pod stuck `CrashLoopBackOff` with `exec format error` in its events | An image built for the wrong CPU architecture landed on the (amd64) node | This is exactly why `demo-up.sh` builds with `--platform linux/amd64` explicitly — if you build images by hand outside the script, pass that flag too. |
| A pod briefly shows `Terminating` and rollouts look stuck | Normal pod-replacement flake during a rolling update, not a real failure | Give it a few seconds and re-check; it resolves on its own. Only worth investigating if it persists past a minute or two. |
| `make demo-down`'s wait loop seems to be watching load balancers that aren't ours | It isn't a bug: the ALB sweep in `demo-down.sh` counts **every** load balancer in the region | This is correct *because* the demo runs in a fresh, dedicated AWS account — any ELB in the region is guaranteed to be this project's. **Do not run these scripts against a shared/multi-project AWS account** without narrowing that check first. |

## 6. Going deeper

- [ADR-0009 — EKS over ECS](adr/0009-eks-over-ecs.md) — why EKS, why
  Terraform, the economics, and the IAM decisions this stack makes.
- [Kubernetes & Helm primer](kubernetes-primer.md) — the chart this
  infrastructure runs; nothing in it changed to reach AWS beyond a values
  file.
- Terraform docs: [S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3),
  [`terraform-aws-modules/vpc`](https://registry.terraform.io/modules/terraform-aws-modules/vpc/aws/latest),
  [`terraform-aws-modules/eks`](https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest)
- AWS docs: [IAM Roles for Service Accounts (IRSA)](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html),
  [GitHub OIDC federation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect),
  [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/)
