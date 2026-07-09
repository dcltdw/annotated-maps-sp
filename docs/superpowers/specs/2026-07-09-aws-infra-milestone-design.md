# Milestone 3 — AWS Infrastructure as Code — Design

- **Date:** 2026-07-09
- **Status:** Approved design, pending implementation plans
- **Slice:** Roadmap Milestone 3 (board card "Milestone 3 — AWS infrastructure as code")
- **Roadmap contract (ROADMAP.md):** `terraform apply` to a working,
  load-balanced deployment on EKS; `terraform destroy` back to zero;
  plan/validate/lint running in CI on every infra PR; the ADR published.

## Context

Milestone 1 produced the portable asset: a Helm chart proven on kind.
Milestone 3 proves the portability claim — the same chart, deployed to real
AWS infrastructure defined entirely in Terraform, spun up on demand and torn
down to zero. Unlike Milestones 1–2 (free tiers), this milestone spends real
money and touches a real AWS account, so cost guardrails and an explicit
account checkpoint are part of the design, not an afterthought.

Decisions locked during brainstorming:

1. **Fresh AWS account**, created at an explicit user checkpoint (like the
   M2 Grafana gate). Budget alarms are the first thing applied.
2. **Budget-boxed live verification:** expect ~3–6 apply/destroy debug
   cycles, then ONE clean documented up→exercise→destroy run as the proof.
   Hard ceiling **$15** (stop and regroup), budget alarm at **$10**.
3. **Blanket apply/destroy authorization within the ceiling**, under two
   standing rules: never end a work session with billable infra up (destroy
   unconditionally, even on failure), and report each cycle's cost.
4. **Module sourcing — hybrid:** community modules
   (`terraform-aws-modules/vpc`, `/eks`) for commodity plumbing; ALL IAM
   hand-written (the OIDC provider + CI role, the IRSA role + trust policy,
   ECR, budgets). The IAM files are the exhibit.
5. **Orchestration — layered:** Terraform owns infrastructure only;
   `make demo-up` / `demo-down` sequence Terraform + kubeconfig + Helm +
   image push. Terraform never manages Helm releases (destroy-time flake
   source; and the ALB-orphan teardown hang is designed out by ordering).
6. **Two PRs** with the account checkpoint between: PR-1 static (no account
   needed), PR-2 live (iteration + evidence + roadmap flip).

## Goals

1. A complete demo environment in Terraform: VPC, EKS, ECR, IAM, budgets —
   `make demo-up` to a working load-balanced app, `make demo-down` to zero.
2. The IAM story as centerpiece: GitHub Actions → AWS via **OIDC federation**
   (no long-lived keys), pods → AWS via **IRSA** (least privilege), and the
   operator's laptop on **Identity Center SSO** short-lived credentials —
   no long-lived keys *anywhere*.
3. Cost guardrails as deliverable: budgets + alarms in Terraform, tagging,
   ephemeral-by-design, a repeat-safe teardown, and a cost-reporting target.
4. Static verification in CI on every infra change; live verification once,
   documented with evidence.
5. ADR-0009 (EKS over ECS + ephemeral economics) published.

## Non-goals (named, mapped)

- **No Route53 / TLS / domain** — the demo serves HTTP on the raw ALB DNS
  name; stated limitation, revisit if a domain ever exists.
- **No CI-driven apply or image pipeline** — CI gets read-only *plan*;
  the one-button pipeline (build→push→deploy→test→destroy) is Milestone 4.
- **No Trivy/SBOM gates** — Milestone 4.
- **No multi-environment workspaces** — one `demo` environment.
- **No EKS add-on zoo** — no external-dns, cert-manager, etc. Only the
  aws-load-balancer-controller, which the Ingress requires.
- **No app-pod IAM roles** — the app needs zero AWS permissions (DB is
  Neon, no S3). The IRSA showcase is the ALB controller's role, a real
  need; ADR-0009 says so plainly.

## Design

### 1. Repo layout

```
deploy/terraform/bootstrap/     S3 state bucket (+ versioning, encryption).
                                Local state, applied once, ~30 lines.
deploy/terraform/demo/          the environment (S3 backend):
  backend.tf                    S3 backend w/ native lockfile (TF >= 1.10 —
                                no DynamoDB lock table needed)
  providers.tf, versions.tf     aws provider, region us-east-1, default tags
  network.tf                    community VPC module: 2 AZs, public+private
                                subnets, ONE NAT gateway (cost decision,
                                commented)
  eks.tf                        community EKS module: 1 managed node group,
                                2x t3.medium, public API endpoint (ephemeral
                                demo; trade-off commented)
  iam-ci.tf                     HAND-WRITTEN: GitHub OIDC provider + the
                                annotated-maps-ci role (see §3)
  iam-irsa.tf                   HAND-WRITTEN: IRSA role + trust policy for
                                the aws-load-balancer-controller (see §3)
  ecr.tf                        two repos (api, web), scan-on-push,
                                force_delete for clean teardown
  budgets.tf                    $10 monthly budget, alerts at 50/80/100% +
                                forecast alert, to the account email
  outputs.tf                    cluster name, region, ECR URLs, IRSA role
                                ARN, OIDC role ARN
scripts/demo-up.sh              orchestration (called by make demo-up)
scripts/demo-down.sh            teardown (called by make demo-down)
deploy/helm/annotated-maps/values-demo.yaml   EKS/ALB values (§4)
docs/adr/0009-eks-over-ecs.md
docs/aws-primer.md              newcomer primer + live-run runbook
```

Flat files over premature module nesting: the environment is one stack, and
the hand-written IAM files are meant to be read.

### 2. The stack

- **Region:** us-east-1. **Tags** (default_tags on the provider):
  `project=annotated-maps, env=demo, ephemeral=true, managed-by=terraform`.
- **VPC:** `terraform-aws-modules/vpc` — 2 AZs, public subnets (ALB),
  private subnets (nodes), single NAT gateway. Subnet tags for ALB discovery
  (`kubernetes.io/role/elb` / `internal-elb`).
- **EKS:** `terraform-aws-modules/eks` — current stable k8s version, one
  managed node group (2× t3.medium, ON_DEMAND; spot noted as an option but
  not used — debug cycles on spot reclaims cost more than they save at this
  scale), public endpoint, cluster-creator admin access, IRSA/OIDC provider
  enabled (the module creates the cluster OIDC provider; our hand-written
  trust policies consume it).
- **ECR:** `annotated-maps-api` + `annotated-maps-web`, `scan_on_push`,
  `force_delete = true` (repos with images must not block destroy).

### 3. IAM (the centerpiece — hand-written, commented)

- **CI (OIDC federation):** an `aws_iam_openid_connect_provider` for
  `token.actions.githubusercontent.com`, plus role `annotated-maps-ci` whose
  trust policy pins `aud = sts.amazonaws.com` and
  `sub = repo:dcltdw/annotated-maps-sp:*` restricted to non-fork refs
  (`ref:refs/heads/main` + `pull_request` events from this repo only).
  Permissions: **read-only plan** — state-bucket read, and `Describe*/Get*/
  List*` on ec2/eks/iam/ecr/budgets. CI can *plan*, never *apply*; the
  apply pipeline is Milestone 4's story and will get a separate role.
- **IRSA (pods):** role `annotated-maps-alb-controller` with a trust policy
  binding the cluster OIDC provider to
  `system:serviceaccount:kube-system:aws-load-balancer-controller`, holding
  the controller's published IAM policy (vendored JSON, pinned version).
  This is the least-privilege-pods demonstration: the ONLY pod with AWS
  permissions is the one that needs them.
- **Operator (laptop):** IAM Identity Center (SSO) — created at the
  checkpoint, used via `aws configure sso` + `aws sso login`. Short-lived
  credentials locally; combined with OIDC in CI and IRSA in-cluster, there
  are **no long-lived AWS keys anywhere in the system**.

### 4. Chart additions (small, kind-compatible)

- `ingress.annotations` passthrough in `templates/ingress.yaml` (empty
  default — kind behavior unchanged; helm-unittest covers present/absent).
- `values-demo.yaml`: `ingress.className: alb`; annotations
  `alb.ingress.kubernetes.io/scheme: internet-facing`,
  `alb.ingress.kubernetes.io/target-type: ip`; image repos = ECR URLs
  (tag set by demo-up); `postgres.enabled: false`;
  `seed.refreshOnDeploy: true` (it's a demo); `secureSslRedirect: "false"`
  + `allowedHosts: ".elb.amazonaws.com"` (Django subdomain wildcard —
  HTTP-only on the raw ALB hostname, no domain; stated limitation).
- **Host-rule note:** the Ingress template's host-matched rule stays; demo-up
  cannot know the ALB hostname before the Ingress exists, so `values-demo`
  sets `ingress.host: ""` and the template omits the `host:` key when empty
  (matches all hosts — one small template conditional, unit-tested).

### 5. `make demo-up` / `demo-down` (scripts/demo-up.sh, demo-down.sh)

**demo-up:** `terraform apply` → `aws eks update-kubeconfig` → helm-install
aws-load-balancer-controller (official chart, serviceAccount annotated with
the IRSA role ARN from `terraform output`) → `docker build` + push api/web
images to ECR (`--platform linux/amd64` — the laptop is arm64) → helm
upgrade --install the app chart with `values-demo.yaml`, ECR refs, and the
Neon **demo-branch** DATABASE_URL prompted at runtime (never stored) → poll
the Ingress for the ALB hostname → smoke: `curl /api/v1/health` + `/` on the
ALB DNS → print the URL + reminder that the meter is running.

**demo-down (the safety-critical path):** helm-uninstall the app → **poll
until the ALB and its target groups are actually gone** (the controller
deletes them async; destroying the VPC while they exist is the classic
hang) → helm-uninstall the controller → `terraform destroy` → verify:
`terraform state list` empty + a scripted post-destroy sweep
(`aws elbv2 describe-load-balancers`, `ec2 describe-nat-gateways`,
`eks list-clusters` — all empty). Every step tolerates already-gone
resources: **demo-down is safe to run repeatedly from any half-failed
state.**

**make demo-cost:** Cost Explorer query (`aws ce get-cost-and-usage`)
filtered by the project tag, printed per-service — the per-cycle cost
report and the receipt for the evidence bundle.

### 6. Cost guardrails

- In Terraform: AWS Budgets — $10/month, actual alerts at 50/80/100%,
  plus a forecast alert; delivered to the account email.
- Session rules (in the primer's runbook AND the plans): never end a
  session with infra up; on any failure, run demo-down before stopping;
  report each cycle's cost via demo-cost. Ceiling $15 → stop and regroup.
- Everything tagged; `demo-cost` and the post-destroy sweep make "back to
  zero" verifiable, not asserted.

### 7. Verification matrix

- **Static (PR-1, CI job `infra`, no AWS account):** `terraform fmt -check`,
  `terraform init -backend=false` + `validate` (both dirs), `tflint`;
  helm-unittest for the chart additions rides the existing `helm` job.
  Runner installs terraform + tflint pinned, mirroring the promtool
  pattern.
- **Plan-in-CI (activates in PR-2, needs the account):** the `infra` job
  gains an OIDC-authenticated `terraform plan` step, gated to same-repo
  events (never fork PRs). Proves the OIDC role works — the roadmap's
  "plan on every infra PR" contract.
- **Live (PR-2):** budget-boxed iteration to green, then ONE clean
  documented run: demo-up → exercise (browse the app on the ALB URL, run
  synthetic traffic, screenshot app + EKS console + `kubectl get pods`) →
  demo-down (screenshot destroy completing + the post-destroy sweep + the
  cost receipt). The evidence bundle lands in `docs/img/` (or a docs page)
  and becomes the ROADMAP proof link.

### 8. ADR-0009 — EKS over ECS

House style. Honest content: ECS+Fargate would be cheaper and simpler for
one small app; EKS is chosen because the M1 Helm chart is the asset whose
portability this milestone proves (kind → EKS as a values file), and
Kubernetes-on-AWS is the market-relevant skill. Records: the ephemeral-vs-
always-on economics (~$180/mo always-on vs ~$2/demo ephemeral), and the
app-needs-no-IRSA note (§ Non-goals) so least-privilege reads as a decision,
not a gap.

### 9. Docs

`docs/aws-primer.md`, in the kubernetes-primer style: the mental model
(account → VPC → EKS → the three no-long-lived-keys identities), what each
Terraform file does with pointers, the demo-up/down/cost commands, the
live-run protocol (runbook), and a troubleshooting table led by the
ALB-orphan destroy hang, IAM propagation delays, and ECR auth expiry.
README gets one line under "Run it on Kubernetes" pointing at the primer
(full README/ROADMAP flip happens in PR-2 with the evidence).

### 10. Checkpoint (user, between PR-1 and PR-2)

1. Create the AWS account; MFA on root.
2. Enable IAM Identity Center; create the admin permission set + user;
   `aws configure sso` locally (profile name handed to the agent).
3. Create a Neon **demo branch**; connection string supplied at demo-up
   prompts, never committed, never pasted into chat logs.
4. Agent then applies `bootstrap/` (state bucket) and `budgets.tf` first,
   and confirms the alarm emails arrive before any EKS spend.
5. Local tooling authorized for brew-install: `terraform` (chosen over
   OpenTofu for market recognition; noted in ADR-0009), `tflint`, `awscli`.

### 11. PR slicing

- **PR-1 (static):** everything in §1–§4 + §7-static + ADR + primer +
  demo-up/down scripts. All CI green without an AWS account.
- **PR-2 (live):** plan-in-CI activation, fixes from the iteration cycles,
  the evidence bundle, README/ROADMAP flip, board card → Done.

## Risks & mitigations

- **Destroy hang via orphaned ALB** — designed out by demo-down ordering +
  the wait-for-ALB-deletion poll; primer troubleshooting entry.
- **Fresh-account service quotas** (rare for one small cluster) — if an
  apply fails on quota, it's a checkpoint item (console request), not a
  code fix; noted in the primer.
- **Cost overrun** — budget alarms live before EKS exists; never-leave-up
  rule; $15 hard ceiling with stop-and-regroup.
- **First-apply failures burning budget** — expected and budgeted (3–6
  cycles); static validation + plan reviews before every apply keep cycles
  short.
- **arm64 laptop vs amd64 nodes** — `--platform linux/amd64` in demo-up's
  builds; primer note (a classic silent CrashLoop otherwise).

## Testing summary

Static: fmt/validate/tflint in CI (both TF dirs); helm-unittest for the
ingress-annotations + empty-host conditionals; scripts shellcheck'd. Live:
OIDC plan job green on a real PR; one documented up→exercise→destroy with
evidence + cost receipt; post-destroy sweep proves zero.
