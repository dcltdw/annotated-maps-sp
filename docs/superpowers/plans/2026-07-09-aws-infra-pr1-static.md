# Milestone 3 PR-1 — Terraform + Chart + Scripts (Static) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The complete AWS demo environment as code — Terraform stacks, hand-written IAM, chart additions, demo-up/down/cost orchestration, CI checks, ADR, primer — all verified statically, no AWS account.

**Architecture:** Two Terraform stacks: `bootstrap/` (S3 state bucket, local state, run once) and `demo/` (everything else, S3 backend with native lockfile). Community modules for VPC/EKS commodity; ALL IAM hand-written (the exhibit). Terraform owns infrastructure only — `scripts/demo-up.sh`/`demo-down.sh` sequence terraform + kubeconfig + helm + ECR pushes, with teardown ordered to prevent the orphaned-ALB destroy hang.

**Tech Stack:** Terraform ≥ 1.10 (S3 native lockfile), terraform-aws-modules/vpc + /eks, aws-load-balancer-controller (Helm), ECR, AWS Budgets, tflint, shellcheck, helm-unittest.

**Spec:** `docs/superpowers/specs/2026-07-09-aws-infra-milestone-design.md` — read before starting any task.

## PRE-FLIGHT (controller): tooling gate

`terraform`, `tflint`, `awscli`, `shellcheck` are NOT installed. BLOCK and ask the user to authorize `brew install terraform tflint awscli shellcheck` before Task 1 (M1 precedent: user runs or explicitly authorizes brew). No AWS account is needed for this plan — only the binaries.

## Global Constraints

- **No AWS account, no credentials, no `terraform plan/apply` in this PR** — static only: `fmt`, `init -backend=false`, `validate`, `tflint`, `shellcheck`, helm-unittest.
- Region **us-east-1**. Default tags on every resource: `project=annotated-maps, env=demo, ephemeral=true, managed-by=terraform`.
- Terraform `required_version = ">= 1.10"` (S3 **native lockfile** — `use_lockfile = true`; NO DynamoDB anywhere).
- Module pins: `terraform-aws-modules/vpc/aws ~> 5.0`, `terraform-aws-modules/eks/aws ~> 20.0`, provider `aws ~> 5.0`. These majors' input names are used verbatim below. A newer major is an acceptable upgrade ONLY if you adapt inputs per that major's docs and say so in your report — never silently, never changing the architecture (2 AZ / 1 NAT / 2× t3.medium / public endpoint / IRSA on).
- IAM is HAND-WRITTEN — no IAM from community modules beyond what the EKS module creates for cluster/nodes internally, and no `iam-role-for-service-accounts` wrapper modules. Trust policies are explicit `jsonencode` blocks with comments.
- CI can *plan*, never *apply*: the CI role's permissions are read-only (inline policy below) — do not attach broader managed policies.
- Chart changes must keep kind behavior byte-identical with default values (annotations empty → no `annotations:` key; `ingress.host` non-empty → host rule as today). `make helm-checks` green.
- Scripts: `bash`, `set -euo pipefail`, shellcheck-clean, and **`demo-down.sh` must be safe to run repeatedly from any half-failed state** (every step tolerates already-gone).
- Images build with `--platform linux/amd64` (dev laptop is arm64; nodes are t3 = amd64).
- Repo conventions: `Co-Authored-By` model trailer on commits; PR body sections `## Summary / ## Provenance / ## Reasoning / ## Testing / ## Risk & rollback`.

## File Structure

```
deploy/terraform/bootstrap/main.tf          state bucket (local state)
deploy/terraform/demo/versions.tf           terraform + provider pins
deploy/terraform/demo/backend.tf            S3 backend + use_lockfile
deploy/terraform/demo/providers.tf          region + default_tags
deploy/terraform/demo/variables.tf          region, cluster_name, budget email
deploy/terraform/demo/network.tf            VPC module
deploy/terraform/demo/eks.tf                EKS module
deploy/terraform/demo/ecr.tf                two repos
deploy/terraform/demo/iam-ci.tf             GitHub OIDC provider + CI role
deploy/terraform/demo/iam-irsa.tf           ALB-controller IRSA role
deploy/terraform/demo/policies/alb-controller-iam-policy.json  (vendored)
deploy/terraform/demo/budgets.tf            $10 budget + alerts
deploy/terraform/demo/outputs.tf
deploy/helm/annotated-maps/templates/ingress.yaml   (+annotations, +empty-host)
deploy/helm/annotated-maps/values.yaml              (+ingress.annotations: {})
deploy/helm/annotated-maps/values-demo.yaml         (new)
deploy/helm/annotated-maps/tests/workloads_test.yaml (+2 tests)
scripts/demo-up.sh, scripts/demo-down.sh, scripts/demo-cost.sh
Makefile                                    (+demo-up/demo-down/demo-cost)
.github/workflows/ci.yml                    (+infra job)
docs/adr/0009-eks-over-ecs.md
docs/aws-primer.md
README.md                                   (one pointer line)
```

---

### Task 1: Terraform skeleton — bootstrap stack + demo stack base

**Files:**
- Create: `deploy/terraform/bootstrap/main.tf`
- Create: `deploy/terraform/demo/versions.tf`, `demo/backend.tf`, `demo/providers.tf`, `demo/variables.tf`

**Interfaces:**
- Produces: variables `region` (default `us-east-1`), `cluster_name` (default `annotated-maps-demo`), `budget_alert_email` (no default, `type = string`); the state bucket name `annotated-maps-tf-state-<ACCOUNT_ID>` pattern (bootstrap outputs it); backend config consumed at `init` time in PR-2.

- [ ] **Step 1: Bootstrap stack**

```hcl
# deploy/terraform/bootstrap/main.tf
# One-time state-bucket bootstrap. Deliberately LOCAL state (the chicken/egg:
# the bucket that stores state can't store its own). Applied once in PR-2;
# its local tfstate is gitignored. ~Zero cost (S3 pennies).
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = {
      project    = "annotated-maps"
      env        = "demo"
      ephemeral  = "true"
      managed-by = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "tf_state" {
  bucket = "annotated-maps-tf-state-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket                  = aws_s3_bucket.tf_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "state_bucket" {
  value = aws_s3_bucket.tf_state.bucket
}
```

Also add to the repo root `.gitignore` (create the stanza if absent):

```
# terraform local artifacts
**/.terraform/
*.tfstate
*.tfstate.backup
*.tfplan
```

- [ ] **Step 2: Demo stack base**

```hcl
# deploy/terraform/demo/versions.tf
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}
```

```hcl
# deploy/terraform/demo/backend.tf
# S3 backend with Terraform >= 1.10 NATIVE lockfile — no DynamoDB table.
# The bucket doesn't exist until PR-2's bootstrap apply; static checks run
# `init -backend=false`, so this block is inert in CI.
terraform {
  backend "s3" {
    # bucket is account-specific: supplied at init time in PR-2 via
    #   terraform init -backend-config="bucket=annotated-maps-tf-state-<ACCOUNT_ID>"
    key          = "demo/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
  }
}
```

```hcl
# deploy/terraform/demo/providers.tf
provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project    = "annotated-maps"
      env        = "demo"
      ephemeral  = "true"
      managed-by = "terraform"
    }
  }
}
```

```hcl
# deploy/terraform/demo/variables.tf
variable "region" {
  description = "AWS region for the demo environment."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name (also used in resource names and tags)."
  type        = string
  default     = "annotated-maps-demo"
}

variable "budget_alert_email" {
  description = "Email for AWS Budgets alerts. No default on purpose: supplied at apply time, never committed."
  type        = string
}
```

- [ ] **Step 3: Verify statically**

Run (from repo root):
```bash
terraform fmt -check -recursive deploy/terraform
(cd deploy/terraform/bootstrap && terraform init -backend=false && terraform validate)
(cd deploy/terraform/demo && terraform init -backend=false && terraform validate)
```
Expected: fmt silent; both `validate` report `Success!` (demo has no resources yet — that's fine; `variables.tf` alone validates).

- [ ] **Step 4: Commit**

```bash
git add deploy/terraform .gitignore
git commit -m "feat(infra): Terraform skeleton — bootstrap state bucket + demo stack base"
```

---

### Task 2: Network, EKS, ECR (community modules)

**Files:**
- Create: `deploy/terraform/demo/network.tf`, `demo/eks.tf`, `demo/ecr.tf`

**Interfaces:**
- Consumes: `var.region`, `var.cluster_name` (Task 1).
- Produces (module outputs used by Task 3): `module.vpc.vpc_id`, `module.vpc.private_subnets`, `module.vpc.public_subnets`, `module.eks.cluster_name`, `module.eks.oidc_provider` (issuer URL sans `https://`), `module.eks.oidc_provider_arn`; resources `aws_ecr_repository.api` / `.web`.

- [ ] **Step 1: network.tf**

```hcl
# deploy/terraform/demo/network.tf
# Community module for commodity plumbing (ADR-0009 / spec fork 1): the
# subnet arithmetic isn't the exhibit — the IAM files are.
data "aws_availability_zones" "available" {
  state = "available"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "annotated-maps-demo"
  cidr = "10.0.0.0/16"

  azs             = slice(data.aws_availability_zones.available.names, 0, 2)
  public_subnets  = ["10.0.0.0/20", "10.0.16.0/20"]
  private_subnets = ["10.0.128.0/20", "10.0.144.0/20"]

  # COST DECISION: one NAT gateway, not per-AZ (~$0.045/hr each). An
  # ephemeral demo does not need AZ-fault-tolerant egress.
  enable_nat_gateway = true
  single_nat_gateway = true

  # ALB controller discovers subnets by these role tags.
  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}
```

- [ ] **Step 2: eks.tf**

```hcl
# deploy/terraform/demo/eks.tf
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.31" # newest supported at pin time; bump if the module rejects it

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Ephemeral demo, no bastion/VPN: public API endpoint (spec §2 trade-off).
  cluster_endpoint_public_access = true

  # The operator identity that runs terraform apply gets cluster-admin.
  enable_cluster_creator_admin_permissions = true

  # IRSA: creates the cluster's OIDC provider; our hand-written trust
  # policies (iam-irsa.tf) consume it.
  enable_irsa = true

  cluster_addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = {}
  }

  eks_managed_node_groups = {
    default = {
      # 2x t3.medium ON_DEMAND: spot reclaims mid-debug-cycle cost more than
      # they save at this scale (spec §2).
      instance_types = ["t3.medium"]
      capacity_type  = "ON_DEMAND"
      min_size       = 2
      max_size       = 2
      desired_size   = 2
    }
  }
}
```

- [ ] **Step 3: ecr.tf**

```hcl
# deploy/terraform/demo/ecr.tf
resource "aws_ecr_repository" "api" {
  name = "annotated-maps-api"
  # Ephemeral env: repos holding images must never block terraform destroy.
  force_delete = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "web" {
  name = "annotated-maps-web"
  force_delete = true
  image_scanning_configuration { scan_on_push = true }
}
```

- [ ] **Step 4: Verify** — `terraform fmt -check -recursive deploy/terraform`, then `(cd deploy/terraform/demo && terraform init -backend=false && terraform validate)`. NOTE: `init -backend=false` DOES download the two modules + provider (network egress, no credentials) — expected. Expected: `Success!`.

- [ ] **Step 5: Commit**

```bash
git add deploy/terraform/demo
git commit -m "feat(infra): VPC, EKS, ECR — community modules for the commodity layer"
```

---

### Task 3: The IAM centerpiece + budgets + outputs (hand-written)

**Files:**
- Create: `deploy/terraform/demo/iam-ci.tf`, `demo/iam-irsa.tf`, `demo/policies/alb-controller-iam-policy.json`, `demo/budgets.tf`, `demo/outputs.tf`

**Interfaces:**
- Consumes: `module.eks.oidc_provider`, `module.eks.oidc_provider_arn` (Task 2).
- Produces: outputs `ci_role_arn`, `alb_controller_role_arn`, `ecr_api_url`, `ecr_web_url`, `cluster_name`, `region`, `vpc_id` (consumed by Task 5's scripts and PR-2).

- [ ] **Step 1: iam-ci.tf (GitHub OIDC federation — no long-lived keys)**

```hcl
# deploy/terraform/demo/iam-ci.tf
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

    # Only THIS repo, and only its own events: pushes to main and same-repo
    # pull_request runs. Fork PRs present a different sub and are refused.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:dcltdw/annotated-maps-sp:ref:refs/heads/main",
        "repo:dcltdw/annotated-maps-sp:pull_request",
      ]
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
```

- [ ] **Step 2: iam-irsa.tf (least-privilege pods)**

```hcl
# deploy/terraform/demo/iam-irsa.tf
# IRSA for the aws-load-balancer-controller — the ONLY pod in the cluster
# with AWS permissions, because it's the only one that needs them (the app
# talks to Neon over TLS; ADR-0009 records this). The trust policy binds the
# role to exactly one ServiceAccount in exactly one cluster.

data "aws_iam_policy_document" "alb_controller_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
  }
}

resource "aws_iam_role" "alb_controller" {
  name               = "annotated-maps-alb-controller"
  assume_role_policy = data.aws_iam_policy_document.alb_controller_trust.json
}

resource "aws_iam_role_policy" "alb_controller" {
  name = "alb-controller"
  role = aws_iam_role.alb_controller.id
  # Vendored from the controller release (see the file header for version/URL)
  # rather than fetched at apply time: pinned, reviewable, diffable.
  policy = file("${path.module}/policies/alb-controller-iam-policy.json")
}
```

- [ ] **Step 3: Vendor the controller IAM policy**

Download the policy matching the current controller release (v2.x line):

```bash
curl -fsSL -o deploy/terraform/demo/policies/alb-controller-iam-policy.json \
  https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.8.2/docs/install/iam_policy.json
python3 -m json.tool deploy/terraform/demo/policies/alb-controller-iam-policy.json > /dev/null
```

Then check the newest v2 release tag (`gh api repos/kubernetes-sigs/aws-load-balancer-controller/releases/latest --jq .tag_name`) and use THAT tag's file instead if newer — record the tag you vendored in your report AND as a comment line you add at the top of… JSON has no comments, so record it in `iam-irsa.tf`'s comment block: append `# Vendored: <tag>` above the `file(...)` line. Task 5's controller chart install must use a chart whose appVersion matches this major/minor line.

- [ ] **Step 4: budgets.tf**

```hcl
# deploy/terraform/demo/budgets.tf
# The guardrail. Applied FIRST in PR-2 (before any EKS spend exists):
#   terraform apply -target=aws_budgets_budget.demo
resource "aws_budgets_budget" "demo" {
  name         = "annotated-maps-demo"
  budget_type  = "COST"
  limit_amount = "10"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
```

- [ ] **Step 5: outputs.tf**

```hcl
# deploy/terraform/demo/outputs.tf
output "region" {
  value = var.region
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "ecr_api_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_web_url" {
  value = aws_ecr_repository.web.repository_url
}

output "alb_controller_role_arn" {
  value = aws_iam_role.alb_controller.arn
}

output "ci_role_arn" {
  value = aws_iam_role.ci.arn
}
```

- [ ] **Step 6: Verify** — fmt + `init -backend=false` + `validate` as in Task 2. Expected `Success!`.

- [ ] **Step 7: Commit**

```bash
git add deploy/terraform/demo
git commit -m "feat(infra): hand-written IAM — GitHub OIDC CI role, ALB-controller IRSA, budgets"
```

---

### Task 4: Chart additions — ingress annotations, empty-host, values-demo

**Files:**
- Modify: `deploy/helm/annotated-maps/templates/ingress.yaml`, `deploy/helm/annotated-maps/values.yaml`
- Create: `deploy/helm/annotated-maps/values-demo.yaml`
- Test: `deploy/helm/annotated-maps/tests/workloads_test.yaml` (append 2 tests)

**Interfaces:**
- Produces: values keys `ingress.annotations` (map, default `{}`) and the empty-`host` behavior (`ingress.host: ""` → no `host:` key → matches all hosts). `values-demo.yaml` consumed by Task 5's demo-up.

- [ ] **Step 1: Failing tests** — append to `tests/workloads_test.yaml`:

```yaml
  - it: ingress renders annotations when set and omits the block by default
    template: templates/ingress.yaml
    set:
      ingress:
        annotations:
          alb.ingress.kubernetes.io/scheme: internet-facing
    asserts:
      - equal:
          path: metadata.annotations["alb.ingress.kubernetes.io/scheme"]
          value: internet-facing
  - it: ingress omits the host key entirely when host is empty (ALB DNS unknown pre-create)
    template: templates/ingress.yaml
    set:
      ingress:
        host: ""
    asserts:
      - notExists:
          path: spec.rules[0].host
      - equal:
          path: spec.rules[0].http.paths[0].path
          value: /api
```

Run `helm unittest deploy/helm/annotated-maps` → the two new tests FAIL (annotations not rendered / host always rendered).

- [ ] **Step 2: Template changes** — in `templates/ingress.yaml`:

Metadata gains (after the `labels:` block):

```yaml
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
```

The rule's host becomes conditional:

```yaml
  rules:
    - {{- if .Values.ingress.host }}
      host: {{ .Values.ingress.host }}
      {{- end }}
      http:
```

(Verify the rendered YAML indentation with `helm template ... --set ingress.host=""` — the `- http:` list-item alignment is the classic mistake; the unittest catches it.)

`values.yaml`: in the existing `ingress:` block add `annotations: {}` with the comment `# extra ingress annotations (e.g. ALB controller settings in values-demo)`.

- [ ] **Step 3: values-demo.yaml**

```yaml
# deploy/helm/annotated-maps/values-demo.yaml
# EKS demo environment (Milestone 3). Image repositories/tags and secrets are
# NOT set here — scripts/demo-up.sh passes them (--set) from terraform
# outputs and runtime prompts. HTTP-only on the raw ALB hostname: no domain,
# no TLS — a stated M3 limitation (spec § Non-goals).
image:
  api:
    pullPolicy: IfNotPresent
  web:
    pullPolicy: IfNotPresent

api:
  env:
    sandboxMode: "true"            # the public demo IS the sandbox
    djangoDebug: "false"
    # Django leading-dot wildcard: any *.elb.amazonaws.com host. The ALB
    # hostname doesn't exist until the Ingress creates it, so it can't be
    # listed literally. Pod-IP entries still come from the downward API.
    allowedHosts: ".elb.amazonaws.com"
    secureSslRedirect: "false"     # HTTP-only demo (no cert without a domain)

ingress:
  className: alb
  host: ""                         # match all hosts; ALB DNS unknown pre-create
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip

postgres:
  enabled: false                   # DB is a Neon branch (URL prompted at demo-up)

monitoring:
  enabled: false                   # no kube-prometheus-stack in the demo env

seed:
  refreshOnDeploy: true            # it's a demo — fresh Boston data every deploy

secrets:
  djangoSecretKey: ""              # supplied by demo-up
  databaseUrl: ""                  # supplied by demo-up (Neon demo branch)
  modToken: ""
```

- [ ] **Step 4: Green** — `helm unittest deploy/helm/annotated-maps` all pass (expect 20 = 18 existing + 2 new; report the actual count). Then full `make helm-checks`; also lint the demo values: `helm lint deploy/helm/annotated-maps -f deploy/helm/annotated-maps/values-demo.yaml --set secrets.databaseUrl=postgis://u:p@h/db`. Confirm default render unchanged: `helm template annotated-maps deploy/helm/annotated-maps | grep -A2 "kind: Ingress" | head` shows no annotations key.

- [ ] **Step 5: Commit**

```bash
git add deploy/helm/annotated-maps
git commit -m "feat(helm): ingress annotations + optional host; values-demo for EKS/ALB"
```

---

### Task 5: demo-up / demo-down / demo-cost scripts + Makefile

**Files:**
- Create: `scripts/demo-up.sh`, `scripts/demo-down.sh`, `scripts/demo-cost.sh` (all `chmod +x`)
- Modify: `Makefile` (+3 targets, `.PHONY` updated)

**Interfaces:**
- Consumes: terraform outputs `region/cluster_name/vpc_id/ecr_api_url/ecr_web_url/alb_controller_role_arn` (Task 3), `values-demo.yaml` (Task 4).
- Produces: `make demo-up`, `make demo-down`, `make demo-cost`. demo-down safe from ANY state.

- [ ] **Step 1: scripts/demo-up.sh**

```bash
#!/usr/bin/env bash
# Bring up the AWS demo environment end-to-end (M3 spec §5).
# Terraform owns infrastructure; this script sequences the rest.
# COST: ~$0.20/hr while up. demo-down when done — never leave it running.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo
CHART=deploy/helm/annotated-maps

for tool in terraform aws helm docker kubectl jq; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

echo "==> terraform apply (infra: VPC, EKS, ECR, IAM, budgets)"
terraform -chdir="$TF_DIR" apply -auto-approve

REGION=$(terraform -chdir="$TF_DIR" output -raw region)
CLUSTER=$(terraform -chdir="$TF_DIR" output -raw cluster_name)
VPC_ID=$(terraform -chdir="$TF_DIR" output -raw vpc_id)
ECR_API=$(terraform -chdir="$TF_DIR" output -raw ecr_api_url)
ECR_WEB=$(terraform -chdir="$TF_DIR" output -raw ecr_web_url)
IRSA_ARN=$(terraform -chdir="$TF_DIR" output -raw alb_controller_role_arn)

echo "==> kubeconfig"
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"

echo "==> aws-load-balancer-controller (IRSA: $IRSA_ARN)"
helm repo add eks https://aws.github.io/eks-charts >/dev/null
helm repo update eks >/dev/null
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName="$CLUSTER" \
  --set region="$REGION" \
  --set vpcId="$VPC_ID" \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set "serviceAccount.annotations.eks\.amazonaws\.com/role-arn=$IRSA_ARN" \
  --wait --timeout 5m

echo "==> build + push images (linux/amd64 — nodes are t3, laptop is arm64)"
TAG=$(git rev-parse --short HEAD)
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ECR_API%%/*}"
docker build --platform linux/amd64 -f backend/Dockerfile -t "$ECR_API:$TAG" .
docker build --platform linux/amd64 -f frontend/Dockerfile -t "$ECR_WEB:$TAG" frontend
docker push "$ECR_API:$TAG"
docker push "$ECR_WEB:$TAG"

echo "==> app secrets (never stored; Neon demo-branch URL + generated key)"
read -r -s -p "Neon demo-branch DATABASE_URL (postgis://...): " DATABASE_URL; echo
DJANGO_SECRET_KEY=$(openssl rand -hex 32)

echo "==> deploy the chart"
helm upgrade --install annotated-maps "$CHART" \
  -n annotated-maps --create-namespace \
  -f "$CHART/values-demo.yaml" \
  --set image.api.repository="$ECR_API" \
  --set image.api.tag="$TAG" \
  --set image.web.repository="$ECR_WEB" \
  --set image.web.tag="$TAG" \
  --set secrets.databaseUrl="$DATABASE_URL" \
  --set secrets.djangoSecretKey="$DJANGO_SECRET_KEY" \
  --wait --timeout 10m

echo "==> waiting for the ALB hostname"
ALB=""
for _ in $(seq 1 60); do
  ALB=$(kubectl -n annotated-maps get ingress annotated-maps \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  [ -n "$ALB" ] && break
  sleep 10
done
[ -n "$ALB" ] || { echo "ALB hostname never appeared — check the controller logs" >&2; exit 1; }

echo "==> smoke (ALB targets take a minute to pass health checks)"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 10 "http://$ALB/api/v1/health" >/dev/null 2>&1; then
    echo "health OK"
    break
  fi
  sleep 10
done
curl -fsS --max-time 10 "http://$ALB/" | grep -qi "<!doctype html" && echo "web OK"

echo
echo "  Demo is UP:  http://$ALB/"
echo "  THE METER IS RUNNING (~\$0.20/hr). Tear down with: make demo-down"
```

- [ ] **Step 2: scripts/demo-down.sh**

```bash
#!/usr/bin/env bash
# Tear the demo environment down to zero. SAFE TO RUN REPEATEDLY from any
# half-failed state: every step tolerates already-gone resources. The
# ordering is the point — the ALB is created out-of-band by the in-cluster
# controller, and terraform destroy HANGS if it still exists (M3 spec §5).
set -uo pipefail   # deliberately NOT -e: teardown continues past failures

cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo

REGION=$(terraform -chdir="$TF_DIR" output -raw region 2>/dev/null || echo "us-east-1")
CLUSTER=$(terraform -chdir="$TF_DIR" output -raw cluster_name 2>/dev/null || echo "annotated-maps-demo")

if aws eks describe-cluster --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1; then
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1 || true

  echo "==> uninstall the app (controller then deletes its ALB)"
  helm uninstall annotated-maps -n annotated-maps --wait --timeout 5m 2>/dev/null || true

  echo "==> waiting for the controller-created ALB to actually delete"
  # Fresh dedicated account: ANY load balancer in the region is ours.
  for _ in $(seq 1 60); do
    COUNT=$(aws elbv2 describe-load-balancers --region "$REGION" \
      --query "length(LoadBalancers)" --output text 2>/dev/null || echo 0)
    [ "$COUNT" = "0" ] && break
    sleep 10
  done

  echo "==> uninstall the controller"
  helm uninstall aws-load-balancer-controller -n kube-system --wait --timeout 5m 2>/dev/null || true
else
  echo "==> cluster not reachable/gone — straight to terraform destroy"
fi

echo "==> terraform destroy"
terraform -chdir="$TF_DIR" destroy -auto-approve

echo "==> post-destroy sweep (all three MUST be empty)"
echo "state:";        terraform -chdir="$TF_DIR" state list 2>/dev/null || true
echo "load balancers:"; aws elbv2 describe-load-balancers --region "$REGION" \
  --query 'LoadBalancers[].LoadBalancerName' --output text 2>/dev/null || true
echo "nat gateways:"; aws ec2 describe-nat-gateways --region "$REGION" \
  --filter Name=state,Values=available,pending \
  --query 'NatGateways[].NatGatewayId' --output text 2>/dev/null || true
echo "eks clusters:"; aws eks list-clusters --region "$REGION" \
  --query 'clusters' --output text 2>/dev/null || true
echo
echo "  If any line above is non-empty, RE-RUN make demo-down; if it persists,"
echo "  see docs/aws-primer.md troubleshooting (orphaned-ALB entry)."
```

- [ ] **Step 3: scripts/demo-cost.sh**

```bash
#!/usr/bin/env bash
# Month-to-date cost, per service. Fresh dedicated account => the account
# total IS the project total (cost-allocation tags lag ~24h and need console
# activation, so we don't filter by tag).
set -euo pipefail
REGION=us-east-1
START=$(date +%Y-%m-01)
END=$(date -v+1d +%Y-%m-%d 2>/dev/null || date -d tomorrow +%Y-%m-%d)  # macOS/Linux
aws ce get-cost-and-usage \
  --time-period Start="$START",End="$END" \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --region "$REGION" \
  --query 'ResultsByTime[0].Groups[?Metrics.UnblendedCost.Amount>`0.001`].[Keys[0],Metrics.UnblendedCost.Amount]' \
  --output table
```

- [ ] **Step 4: Makefile** (near the kind targets, matching style):

```makefile
demo-up: ## AWS demo env: terraform apply + ALB controller + ECR push + deploy (~$$0.20/hr!)
	./scripts/demo-up.sh

demo-down: ## Tear the AWS demo down to zero (safe to re-run from any state)
	./scripts/demo-down.sh

demo-cost: ## Month-to-date AWS spend by service
	./scripts/demo-cost.sh
```

Add all three to `.PHONY`.

- [ ] **Step 5: Verify statically** — `shellcheck scripts/demo-up.sh scripts/demo-down.sh scripts/demo-cost.sh` clean; `bash -n` each; `chmod +x` confirmed (`ls -l scripts/`). NO live execution.

- [ ] **Step 6: Commit**

```bash
git add scripts/demo-up.sh scripts/demo-down.sh scripts/demo-cost.sh Makefile
git commit -m "feat(infra): demo-up/demo-down/demo-cost orchestration (teardown-safe ordering)"
```

---

### Task 6: CI — the `infra` job

**Files:**
- Modify: `.github/workflows/ci.yml` (new job after `helm`)

**Interfaces:**
- Produces: job name `infra` (a future required check; the PR-2 plan adds the OIDC plan step and the ruleset entry).

- [ ] **Step 1: Add the job**

```yaml
  infra:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.10.5"
      - name: terraform fmt
        run: terraform fmt -check -recursive deploy/terraform
      - name: terraform validate (bootstrap)
        run: |
          terraform -chdir=deploy/terraform/bootstrap init -backend=false
          terraform -chdir=deploy/terraform/bootstrap validate
      - name: terraform validate (demo)
        run: |
          terraform -chdir=deploy/terraform/demo init -backend=false
          terraform -chdir=deploy/terraform/demo validate
      - name: tflint
        run: |
          curl -fsSL https://github.com/terraform-linters/tflint/releases/download/v0.53.0/tflint_linux_amd64.zip -o /tmp/tflint.zip
          (cd /tmp && unzip -o tflint.zip && sudo mv tflint /usr/local/bin/)
          tflint --chdir=deploy/terraform/bootstrap
          tflint --chdir=deploy/terraform/demo
      - name: shellcheck demo scripts
        run: shellcheck scripts/demo-up.sh scripts/demo-down.sh scripts/demo-cost.sh
```

(Pin note: use the terraform 1.10.x latest patch and tflint's current release at implementation time if newer — pin to exact versions either way; shellcheck is preinstalled on ubuntu runners.)

- [ ] **Step 2: Validate + commit**

`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` → OK.

```bash
git add .github/workflows/ci.yml
git commit -m "ci: infra job — terraform fmt/validate + tflint + shellcheck"
```

---

### Task 7: ADR-0009, aws-primer, README pointer

**Files:**
- Create: `docs/adr/0009-eks-over-ecs.md`, `docs/aws-primer.md`
- Modify: `README.md` (one line in the "Run it on Kubernetes" section)

- [ ] **Step 1: ADR-0009** — house style (`# ADR-0009: <title>`, `- Status: accepted`, `- Date: 2026-07-09`, Context / Decision / Consequences / Alternatives considered — mirror `docs/adr/0008-*.md`). Required content: EKS chosen because the M1 Helm chart is the asset whose portability M3 proves (kind → EKS as a values file) and Kubernetes-on-AWS is the market-relevant skill; ECS+Fargate honestly cheaper/simpler for one small app (alternative, rejected with respect); Terraform over OpenTofu for market recognition; ephemeral-vs-always-on economics (~$180/mo always-on vs ~$2 per ephemeral demo run); the app-pods-need-no-IAM note (only the ALB controller holds an IRSA role — least privilege as a decision, not a gap).

- [ ] **Step 2: docs/aws-primer.md** — kubernetes-primer.md's structure and voice. Required sections: (1) the mental model — account → VPC (public/private subnets, one NAT) → EKS → the app, and the THREE no-long-lived-keys identities (laptop = Identity Center SSO; CI = GitHub OIDC; pods = IRSA) with a small ASCII diagram; (2) what each Terraform file does, one line each, with paths; (3) the commands — demo-up / demo-down / demo-cost, what each costs, the never-leave-it-up rule; (4) the live-run protocol (runbook): budgets first, per-cycle cost report, $15 ceiling → stop; (5) troubleshooting table with AT MINIMUM: orphaned-ALB destroy hang (symptom: destroy stuck on VPC/subnet deletes → re-run demo-down, it waits for ALB deletion; manual fix: delete ALB + target groups in console then re-destroy), IAM propagation delays (a just-created role failing AssumeRole for ~10s — retry), ECR auth expiry (12h token → re-run the docker login line), arm64 image on amd64 node (CrashLoopBackOff `exec format error` → the `--platform linux/amd64` flag exists for this), Terminating-pod flakes during rollouts.

- [ ] **Step 3: README** — in the "Run it on Kubernetes" section add one line: `Milestone 3 takes the same chart to AWS (Terraform + EKS): see [docs/aws-primer.md](docs/aws-primer.md).` (The full README/ROADMAP proof flip happens in PR-2 with the evidence.)

- [ ] **Step 4: Final static gates (whole PR)** — from repo root: `terraform fmt -check -recursive deploy/terraform`; both dirs `init -backend=false && validate`; `tflint --chdir` both dirs; `shellcheck scripts/demo-*.sh`; `make helm-checks`; `make obs-checks`; backend + frontend suites untouched-but-confirm (`cd backend && uv run pytest -q | tail -1`; `cd frontend && npm run test -- --run 2>&1 | grep "Tests"`). All green.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0009-eks-over-ecs.md docs/aws-primer.md README.md
git commit -m "docs: ADR-0009 (EKS over ECS), AWS primer + runbook, README pointer"
```
