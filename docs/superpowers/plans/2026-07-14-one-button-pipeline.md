# Milestone 4 — One-Button Ephemeral Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `workflow_dispatch` + monthly-scheduled GitHub Actions pipeline that provisions the AWS demo, gates images on Trivy/SBOM, deploys, tests via Playwright against the live ALB, and destroys — teardown guaranteed and triple-alarmed — shipped as eight small single-purpose PRs.

**Architecture:** Phased make targets shared by laptop and CI (`demo-infra-up` / `demo-images` / `demo-app-deploy` / `demo-down`); the workflow's jobs mirror the phases 1:1. An apply-capable `annotated-maps-deployer` role (IAM bounded to the `annotated-maps-*` prefix) is trusted by exactly one unprotected `aws-deploy` GitHub Environment — no job ever waits on a human. Lifecycle events publish to a foundation SNS topic; the email subscription filters `severity=alert`.

**Tech Stack:** GitHub Actions (workflow_dispatch + schedule + Environments + OIDC), Terraform, Trivy (+ CycloneDX SBOM), Neon API (per-run DB branches), Playwright, SNS, actionlint.

**Spec:** `docs/superpowers/specs/2026-07-14-one-button-pipeline-design.md` — read before starting any task.

## Execution model (IMPORTANT — one task = one PR)

Every task below ends by opening its own PR (rigor sections; `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer on commits). Branch each task **off current `main`** with the branch name given in the task. Tasks 1–2–3–5–6 (PRs A/B/C/E/F) are mutually independent — implement in the order written, but do NOT wait for one PR to merge before starting the next *independent* task. Task 4 (PR-D) requires PR-C **merged** first; Task 7 (PR-G) requires B/C/D/E/F merged; Task 8 is the controller-run live phase on PR-G's branch; Task 9 (PR-H) follows the green main run.

## Global Constraints

- **No live AWS/Neon calls in Tasks 1–7** — static verification only (shellcheck, `bash -n`, terraform fmt/validate/tflint, actionlint, YAML/JSON parse, helm-checks where touched). Live execution is Task 8, budget-boxed **$10** (expect 2–4 runs at ~$1–2), never-leave-up, per-run cost line in the ledger.
- Scripts: bash, `set -euo pipefail` (demo-down keeps `set -uo` — NO `-e`), shellcheck-clean, `chmod +x`.
- Secrets NEVER on command lines or in logs: helm gets them via `--set-file`; the Neon API key travels only in an env var to curl; no `set -x` anywhere near secrets.
- IAM naming boundary: everything the deployer role manages matches `annotated-maps-*` (node-group role renamed to fit — Task 4).
- `make demo-up` (the local chained flow) must behave exactly as today, prompt and all.
- Region us-east-1. Makefile style: tabs, `## help` comments, `.PHONY` updated.
- All checks green before each PR opens: relevant static gates + `make helm-checks && make obs-checks` if the chart/Makefile was touched; backend/frontend suites untouched (verify only if their files change).

## File Structure

```
deploy/terraform/demo/eks.tf                (A: create_kms_key=false; D: node-role name)
scripts/demo-infra-up.sh                    (B, new) terraform apply + outputs
scripts/demo-images.sh                      (B, new) login/build/scan-ready/push
scripts/demo-app-deploy.sh                  (B, new) controller+deploy+HARD smoke
scripts/demo-up.sh                          (B) becomes a 4-line chain
scripts/demo-down.sh                        (B: unchanged; E: +neon delete hook)
scripts/demo-cost.sh                        (B) graceful CE-unavailable
Makefile                                    (B) +demo-infra-up/demo-images/demo-app-deploy
deploy/terraform/foundation/sns.tf          (C, new) topic + filtered subscription
deploy/terraform/foundation/outputs.tf      (C: +alerts_topic_arn; D: +deployer_role_arn)
deploy/terraform/foundation/iam-deployer.tf (D, new)
scripts/neon-branch.sh                      (E, new) create|delete
frontend/playwright.alb.config.ts           (F, new)
frontend/e2e-alb/smoke.spec.ts              (F, new)
frontend/package.json                       (F) +"e2e:alb" script
.github/workflows/demo-pipeline.yml         (G, new)
.github/workflows/ci.yml                    (G) +actionlint step in infra job
docs/adr/0010-pipeline-apply-role.md        (G, new)
docs/m4-pipeline.md, docs/aws-primer.md, README.md, ROADMAP.md   (H)
```

---

### Task 1 (PR-A): KMS off — branch `m4-kms-off`

**Files:**
- Modify: `deploy/terraform/demo/eks.tf` (inside the `module "eks"` block)

**Interfaces:**
- Produces: no more per-cluster customer-managed KMS key; nothing else changes.

- [ ] **Step 1:** In `deploy/terraform/demo/eks.tf`, after `enable_irsa = true`, add:

```hcl
  # No customer-managed KMS key for cluster-secrets envelope encryption. The
  # demo holds zero sensitive data and lives for hours; the CMK's only real
  # effect here was a ~$1/mo pending-deletion charge accruing PER RUN, since
  # terraform destroy can only SCHEDULE key deletion (7-30 day window).
  # Control-plane storage is AWS-encrypted regardless. See ADR-0010.
  create_kms_key            = false
  cluster_encryption_config = {}
```

(If `terraform validate` rejects either input name against the pinned `~> 20.0` module, check the resolved module's `variables.tf` in `.terraform/modules/eks/` for the current names — the intent is: no KMS key, no encryption config — and report the actual names used.)

- [ ] **Step 2:** Verify: `terraform fmt -check -recursive deploy/terraform`; `(cd deploy/terraform/demo && terraform init -backend=false && terraform validate)` → Success; `tflint --chdir=deploy/terraform/demo` → clean.
- [ ] **Step 3:** Commit `fix(infra): stop creating a per-cluster KMS key (ends pending-deletion accrual)`; push branch; open PR-A (rigor body; note: verified statically, exercised live by the pipeline in Task 8).

---

### Task 2 (PR-B): phase scripts + hardening — branch `m4-phase-scripts`

**Files:**
- Create: `scripts/demo-infra-up.sh`, `scripts/demo-images.sh`, `scripts/demo-app-deploy.sh` (all `chmod +x`)
- Modify: `scripts/demo-up.sh` (becomes a chain), `scripts/demo-cost.sh` (graceful), `Makefile` (+3 targets)

**Interfaces:**
- Produces: `make demo-infra-up` / `demo-images` / `demo-app-deploy` (used verbatim by Task 7's jobs). Env contract for CI: `IMAGE_TAG` (optional; default `git rev-parse --short HEAD`), `DB_URL_FILE` (path; demo-app-deploy uses it, else prompts), `GITHUB_OUTPUT` (if set, demo-app-deploy appends `alb_url=http://<ALB>`). Smoke failure = **exit 1**.

- [ ] **Step 1: `scripts/demo-infra-up.sh`** — the terraform phase, split from today's demo-up.sh:

```bash
#!/usr/bin/env bash
# Phase 1/3 of the demo bring-up: infrastructure only (M4 spec §6).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo

for tool in terraform aws; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

echo "==> terraform apply (infra: VPC, EKS, ECR, IRSA)"
terraform -chdir="$TF_DIR" apply -auto-approve -input=false
terraform -chdir="$TF_DIR" output
```

- [ ] **Step 2: `scripts/demo-images.sh`** — build + push (the Trivy gate itself lives in the workflow, between build and push; locally this phase just builds and pushes):

```bash
#!/usr/bin/env bash
# Phase 2/3: build and push the app images to ECR (linux/amd64 — t3 nodes).
# IMAGE_TAG env overrides the default git-SHA tag (CI passes the run's SHA).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo

for tool in terraform aws docker; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

REGION=$(terraform -chdir="$TF_DIR" output -raw region)
ECR_API=$(terraform -chdir="$TF_DIR" output -raw ecr_api_url)
ECR_WEB=$(terraform -chdir="$TF_DIR" output -raw ecr_web_url)
TAG=${IMAGE_TAG:-$(git rev-parse --short HEAD)}

echo "==> docker login (ECR)"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ECR_API%%/*}"

echo "==> build (explicit linux/amd64) + push, tag $TAG"
docker build --platform linux/amd64 -f backend/Dockerfile -t "$ECR_API:$TAG" .
docker build --platform linux/amd64 -f frontend/Dockerfile -t "$ECR_WEB:$TAG" frontend
docker push "$ECR_API:$TAG"
docker push "$ECR_WEB:$TAG"
```

- [ ] **Step 3: `scripts/demo-app-deploy.sh`** — controller + chart + HARD-FAILING smoke + `--set-file` secrets:

```bash
#!/usr/bin/env bash
# Phase 3/3: ALB controller + the app chart + a smoke test that GATES.
# Secrets flow via --set-file (never process args). Smoke failure exits 1 —
# "Demo is UP" is printed only when it actually is (M4 hardening).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo
CHART=deploy/helm/annotated-maps

for tool in terraform aws helm kubectl curl; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

REGION=$(terraform -chdir="$TF_DIR" output -raw region)
CLUSTER=$(terraform -chdir="$TF_DIR" output -raw cluster_name)
VPC_ID=$(terraform -chdir="$TF_DIR" output -raw vpc_id)
ECR_API=$(terraform -chdir="$TF_DIR" output -raw ecr_api_url)
ECR_WEB=$(terraform -chdir="$TF_DIR" output -raw ecr_web_url)
IRSA_ARN=$(terraform -chdir="$TF_DIR" output -raw alb_controller_role_arn)
TAG=${IMAGE_TAG:-$(git rev-parse --short HEAD)}

echo "==> kubeconfig"
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"

echo "==> aws-load-balancer-controller (IRSA: $IRSA_ARN)"
helm repo add eks https://aws.github.io/eks-charts >/dev/null
helm repo update eks >/dev/null
# Chart 1.17.1 (appVersion v2.17.1) matches the vendored IAM policy — see
# deploy/terraform/demo/iam-irsa.tf. Unpinned would pull v3.x and mismatch.
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --version 1.17.1 \
  -n kube-system \
  --set clusterName="$CLUSTER" \
  --set region="$REGION" \
  --set vpcId="$VPC_ID" \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set "serviceAccount.annotations.eks\.amazonaws\.com/role-arn=$IRSA_ARN" \
  --wait --timeout 5m

echo "==> app secrets (never stored, never on a command line)"
SECRETS_DIR=$(mktemp -d)
trap 'rm -rf "$SECRETS_DIR"' EXIT
if [ -n "${DB_URL_FILE:-}" ] && [ -f "$DB_URL_FILE" ]; then
  tr -d '[:space:]' < "$DB_URL_FILE" > "$SECRETS_DIR/db"
  echo "    (DATABASE_URL read from \$DB_URL_FILE)"
else
  read -r -s -p "Neon demo-branch DATABASE_URL (postgis://...): " DATABASE_URL; echo
  printf '%s' "$DATABASE_URL" > "$SECRETS_DIR/db"
fi
openssl rand -hex 32 > "$SECRETS_DIR/key"

echo "==> deploy the chart (tag $TAG)"
helm upgrade --install annotated-maps "$CHART" \
  -n annotated-maps --create-namespace \
  -f "$CHART/values-demo.yaml" \
  --set image.api.repository="$ECR_API" \
  --set image.api.tag="$TAG" \
  --set image.web.repository="$ECR_WEB" \
  --set image.web.tag="$TAG" \
  --set-file secrets.databaseUrl="$SECRETS_DIR/db" \
  --set-file secrets.djangoSecretKey="$SECRETS_DIR/key" \
  --wait --timeout 10m

echo "==> waiting for the ALB hostname"
ALB=""
for _ in $(seq 1 60); do
  ALB=$(kubectl -n annotated-maps get ingress annotated-maps \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  [ -n "$ALB" ] && break
  sleep 10
done
[ -n "$ALB" ] || { echo "FAIL: ALB hostname never appeared" >&2; exit 1; }

echo "==> smoke (GATES: exits 1 unless the app actually serves)"
HEALTH_OK=""
for _ in $(seq 1 30); do
  if curl -fsS --max-time 10 "http://$ALB/api/v1/health" >/dev/null 2>&1; then
    HEALTH_OK=1; echo "health OK"; break
  fi
  sleep 10
done
[ -n "$HEALTH_OK" ] || { echo "FAIL: health never returned 200 via the ALB" >&2; exit 1; }
curl -fsS --max-time 10 "http://$ALB/" | grep -qi "<!doctype html" \
  || { echo "FAIL: web root did not serve the SPA" >&2; exit 1; }
echo "web OK"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "alb_url=http://$ALB" >> "$GITHUB_OUTPUT"
fi
echo
echo "  Demo is UP:  http://$ALB/"
echo "  THE METER IS RUNNING (~\$0.20/hr). Tear down with: make demo-down"
```

- [ ] **Step 4: `scripts/demo-up.sh`** becomes the chain (replace the whole body below the header comment):

```bash
#!/usr/bin/env bash
# Bring up the AWS demo environment end-to-end — chains the three phases.
# The CI pipeline runs the same phases as separate jobs (M4 spec §3/§6).
# COST: ~$0.20/hr while up. demo-down when done — never leave it running.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
./scripts/demo-infra-up.sh
./scripts/demo-images.sh
./scripts/demo-app-deploy.sh
```

- [ ] **Step 5: `scripts/demo-cost.sh`** — wrap the `aws ce` call so ingestion lag isn't an error. Replace the final `aws ce ...` invocation with:

```bash
if ! aws ce get-cost-and-usage \
  --time-period Start="$START",End="$END" \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --region "$REGION" \
  --query 'ResultsByTime[0].Groups[?Metrics.UnblendedCost.Amount>`0.001`].[Keys[0],Metrics.UnblendedCost.Amount]' \
  --output table 2>/tmp/demo-cost-err; then
  if grep -q "DataUnavailableException" /tmp/demo-cost-err; then
    echo "Cost Explorer has no data yet (new accounts ingest ~24h behind)."
    echo "Estimate from resource-hours instead: ~\$0.26/hr while the demo is up."
    exit 0
  fi
  cat /tmp/demo-cost-err >&2
  exit 1
fi
```

(Keep the existing `# shellcheck disable=SC2016` comment attached to the query line.)

- [ ] **Step 6: Makefile** — add below `demo-up`, and to `.PHONY`:

```makefile
demo-infra-up: ## Phase 1/3: terraform apply the demo infra
	./scripts/demo-infra-up.sh

demo-images: ## Phase 2/3: build + push images to ECR (IMAGE_TAG env optional)
	./scripts/demo-images.sh

demo-app-deploy: ## Phase 3/3: ALB controller + deploy + gating smoke
	./scripts/demo-app-deploy.sh
```

- [ ] **Step 7:** Verify statically: `shellcheck scripts/demo-*.sh` clean; `bash -n` each; `ls -l scripts/demo-*.sh` shows +x; `make -n demo-up demo-infra-up demo-images demo-app-deploy` resolve. NO live execution.
- [ ] **Step 8:** Commit `refactor(infra): split demo-up into phase targets; smoke gates; --set-file secrets; demo-cost graceful` (this closes three board tickets — say so in the PR body); push `m4-phase-scripts`; open PR-B.

---

### Task 3 (PR-C): foundation SNS — branch `m4-sns`

**Files:**
- Create: `deploy/terraform/foundation/sns.tf`
- Modify: `deploy/terraform/foundation/outputs.tf` (+1 output)

**Interfaces:**
- Produces: topic `annotated-maps-alerts`; output `alerts_topic_arn` (consumed by Task 4's policy and Task 8's `SNS_TOPIC_ARN` repo variable). Message contract: publishes carry a `severity` string attribute, `alert` or `info`; the email subscription filters `alert`.

- [ ] **Step 1: `deploy/terraform/foundation/sns.tf`**

```hcl
# deploy/terraform/foundation/sns.tf
# Lifecycle events for the demo pipeline (M4 spec §5). One topic carries
# everything (demo-ready, run-summary, teardown-failed), each publish tagged
# with a `severity` message attribute. The email subscription filters
# severity=alert — the inbox gets failures only; widen the filter to
# ["alert","info"] to also receive demo-ready/run-summary events.
# Volume is a few messages/month: comfortably $0 (SNS free tier).
resource "aws_sns_topic" "alerts" {
  name = "annotated-maps-alerts"
}

resource "aws_sns_topic_subscription" "email_alerts" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "dcltdw@protonmail.com"
  # Requires a one-time "Confirm subscription" click in the inbox.
  filter_policy = jsonencode({
    severity = ["alert"]
  })
}
```

And in `outputs.tf`:

```hcl
output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
```

- [ ] **Step 2:** Verify: fmt / `(cd deploy/terraform/foundation && terraform init -backend=false && terraform validate)` / `tflint --chdir=deploy/terraform/foundation` — all clean. NO apply (Task 8).
- [ ] **Step 3:** Commit `feat(infra): SNS alerts topic + severity-filtered email subscription`; push `m4-sns`; open PR-C (body notes the confirm-click lands at the Task-8 checkpoint).

---

### Task 4 (PR-D): the deployer role — branch `m4-deployer-role` (REQUIRES PR-C MERGED; branch off updated main)

**Files:**
- Create: `deploy/terraform/foundation/iam-deployer.tf`
- Modify: `deploy/terraform/foundation/outputs.tf` (+1 output), `deploy/terraform/demo/eks.tf` (node-role name into the `annotated-maps-*` boundary)

**Interfaces:**
- Produces: role `annotated-maps-deployer`, output `deployer_role_arn` (Task 8 sets it as repo variable `AWS_DEPLOY_ROLE_ARN`). Trust: ONLY `repo:dcltdw/annotated-maps-sp:environment:aws-deploy`.

- [ ] **Step 1: `deploy/terraform/foundation/iam-deployer.tf`**

```hcl
# deploy/terraform/foundation/iam-deployer.tf
# The pipeline's apply-capable role (ADR-0010). Contrast with annotated-maps-ci
# (iam-ci.tf), which is read-only plan: this role CAN create and destroy the
# demo stack. Honest scoping: terraform apply of VPC+EKS+ECR legitimately
# needs broad service powers, so those are granted per-service — and the
# boundary is enforced where it matters: IAM is restricted to the
# annotated-maps-* prefix, S3 to the state bucket, SNS to the alerts topic.
#
# Trust: exactly one OIDC subject — the unprotected `aws-deploy` GitHub
# Environment. workflow_dispatch/schedule can't be triggered by forks and
# dispatching requires write access; there is deliberately NO required
# reviewer (dispatch IS the confirmation, and a reviewer-gated destroy job
# could hang teardown — see ADR-0010).

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "deployer_trust" {
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

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:dcltdw/annotated-maps-sp:environment:aws-deploy"]
    }
  }
}

resource "aws_iam_role" "deployer" {
  name               = "annotated-maps-deployer"
  assume_role_policy = data.aws_iam_policy_document.deployer_trust.json
}

data "aws_iam_policy_document" "deployer_permissions" {
  # Broad per-service powers the demo stack genuinely needs to create/destroy.
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
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }

  # The hard boundary: IAM only within this project's namespace.
  statement {
    sid    = "IamWithinPrefix"
    effect = "Allow"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/annotated-maps-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/annotated-maps-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/annotated-maps-*",
    ]
  }

  # Read the GitHub OIDC provider (the EKS module reads providers during plan).
  statement {
    sid       = "OidcProviderRead"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviders"]
    resources = ["*"]
  }

  # EKS/ELB/Autoscaling create service-linked roles on first use.
  statement {
    sid       = "ServiceLinkedRoles"
    effect    = "Allow"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/*"]
  }

  # State bucket: read-write (unlike the plan-only CI role).
  statement {
    sid    = "StateReadWrite"
    effect = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.tf_state.arn,
      "${aws_s3_bucket.tf_state.arn}/*",
    ]
  }

  # Lifecycle events: this one topic, publish only.
  statement {
    sid       = "PublishAlerts"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  # The cost line in run-summary.
  statement {
    sid       = "CostRead"
    effect    = "Allow"
    actions   = ["ce:GetCostAndUsage"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deployer" {
  name   = "deploy-demo-stack"
  role   = aws_iam_role.deployer.id
  policy = data.aws_iam_policy_document.deployer_permissions.json
}
```

(If `data.aws_caller_identity.current` already exists in the foundation stack under that name, reuse it — don't declare twice; `state.tf` has one, so **remove the duplicate here** and reference the existing one. Verify with `grep -rn aws_caller_identity deploy/terraform/foundation/`.)

And in `outputs.tf`:

```hcl
output "deployer_role_arn" {
  value = aws_iam_role.deployer.arn
}
```

- [ ] **Step 2: node-role naming into the boundary** — in `deploy/terraform/demo/eks.tf`, inside `eks_managed_node_groups.default`, add:

```hcl
      # The deployer role's IAM boundary is the annotated-maps-* prefix; the
      # module's default node-role name ("default-eks-node-group-...") falls
      # outside it. Name it inside.
      iam_role_name            = "annotated-maps-node"
      iam_role_use_name_prefix = true
```

NOTE for the PR body + Task 8: this changes the node-group role name, so the next live apply replaces the node group — fine for an ephemeral stack that's currently destroyed.

- [ ] **Step 3:** Verify: fmt; validate + tflint on BOTH `foundation` and `demo`; confirm no duplicate `aws_caller_identity`. Commit `feat(infra): apply-capable deployer role, IAM bounded to the annotated-maps-* prefix`; push `m4-deployer-role`; open PR-D.

---

### Task 5 (PR-E): the Neon branch script — branch `m4-neon-branch`

**Files:**
- Create: `scripts/neon-branch.sh` (`chmod +x`)
- Modify: `scripts/demo-down.sh` (delete-if-named hook, ~6 lines)

**Interfaces:**
- Produces: `scripts/neon-branch.sh create <name> <out-file>` (creates the branch, writes the `postgis://` connection string to `<out-file>`) and `scripts/neon-branch.sh delete <name>` (idempotent). Env: `NEON_API_KEY` (required), `NEON_PROJECT_ID` (required), `NEON_DB_NAME` (default `neondb`), `NEON_ROLE_NAME` (default `neondb_owner`). demo-down deletes branch `$NEON_BRANCH` when that env var is set.

- [ ] **Step 1: `scripts/neon-branch.sh`**

```bash
#!/usr/bin/env bash
# Create/delete a Neon database branch for an ephemeral pipeline run
# (M4 spec §4). The API key travels only in the Authorization header; the
# connection string is written to a FILE (for --set-file), never echoed.
#   neon-branch.sh create <branch-name> <out-file>
#   neon-branch.sh delete <branch-name>
set -euo pipefail

API=https://console.neon.tech/api/v2
for tool in curl jq; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done
: "${NEON_API_KEY:?NEON_API_KEY is required}"
: "${NEON_PROJECT_ID:?NEON_PROJECT_ID is required}"
DB_NAME=${NEON_DB_NAME:-neondb}
ROLE_NAME=${NEON_ROLE_NAME:-neondb_owner}

req() { # method path [json-body]
  local method=$1 path=$2 body=${3:-}
  curl -fsS -X "$method" "$API$path" \
    -H "Authorization: Bearer $NEON_API_KEY" \
    -H "Content-Type: application/json" \
    ${body:+-d "$body"}
}

branch_id_by_name() {
  req GET "/projects/$NEON_PROJECT_ID/branches" \
    | jq -r --arg n "$1" '.branches[] | select(.name == $n) | .id'
}

case "${1:-}" in
  create)
    NAME=${2:?branch name required}
    OUT=${3:?output file path required}
    echo "==> creating Neon branch $NAME"
    req POST "/projects/$NEON_PROJECT_ID/branches" \
      "{\"branch\": {\"name\": \"$NAME\"}, \"endpoints\": [{\"type\": \"read_write\"}]}" \
      > /dev/null
    BRANCH_ID=$(branch_id_by_name "$NAME")
    [ -n "$BRANCH_ID" ] || { echo "FAIL: branch $NAME not found after create" >&2; exit 1; }
    # The connection URI for the new branch's endpoint.
    URI=$(req GET "/projects/$NEON_PROJECT_ID/connection_uri?branch_id=$BRANCH_ID&database_name=$DB_NAME&role_name=$ROLE_NAME&pooled=false" \
      | jq -r '.uri')
    [ -n "$URI" ] && [ "$URI" != "null" ] || { echo "FAIL: no connection URI returned" >&2; exit 1; }
    # Django needs the PostGIS scheme.
    printf '%s' "${URI/postgresql:\/\//postgis://}" > "$OUT"
    echo "==> connection string written to $OUT (postgis://, not logged)"
    ;;
  delete)
    NAME=${2:?branch name required}
    BRANCH_ID=$(branch_id_by_name "$NAME" || true)
    if [ -z "$BRANCH_ID" ]; then
      echo "==> Neon branch $NAME not found (already gone) — nothing to delete"
      exit 0
    fi
    echo "==> deleting Neon branch $NAME ($BRANCH_ID)"
    req DELETE "/projects/$NEON_PROJECT_ID/branches/$BRANCH_ID" > /dev/null
    ;;
  *)
    echo "usage: $0 create <name> <out-file> | delete <name>" >&2
    exit 2
    ;;
esac
```

(API-shape guard: the endpoints above — `POST/GET/DELETE /projects/{id}/branches` and `GET /projects/{id}/connection_uri` — are Neon API v2. Verify field names against https://api-docs.neon.tech at implementation time; if `connection_uri` requires different params or the create-response shape differs, adapt and note it in your report. The CONTRACT — create writes a `postgis://` string to the out-file; delete is idempotent — must not change.)

- [ ] **Step 2: demo-down hook** — in `scripts/demo-down.sh`, immediately BEFORE the final "post-destroy sweep" block, add:

```bash
if [ -n "${NEON_BRANCH:-}" ]; then
  echo "==> deleting the per-run Neon branch ($NEON_BRANCH)"
  ./scripts/neon-branch.sh delete "$NEON_BRANCH" || true
fi
```

(demo-down runs without `-e` and the hook is `|| true` — a Neon API blip must never fail teardown. Local runs don't set `NEON_BRANCH`, so nothing changes for them.)

- [ ] **Step 3:** Verify: `shellcheck scripts/neon-branch.sh scripts/demo-down.sh` clean; `bash -n` both; +x bit. NO live API calls (Task 8 exercises it; optional local sanity `NEON_API_KEY=... ./scripts/neon-branch.sh create test-branch /tmp/t && ... delete test-branch` is allowed ONLY if the user has provided the key — otherwise skip).
- [ ] **Step 4:** Commit `feat(infra): per-run Neon branch create/delete + demo-down hook`; push `m4-neon-branch`; open PR-E.

---

### Task 6 (PR-F): Playwright vs the ALB — branch `m4-playwright-alb`

**Files:**
- Create: `frontend/playwright.alb.config.ts`, `frontend/e2e-alb/smoke.spec.ts`
- Modify: `frontend/package.json` (+1 script), `frontend/vite.config.ts` (vitest exclude)

**Interfaces:**
- Produces: `BASE_URL=<url> npm run e2e:alb` (from `frontend/`) — a smoke suite against any live deployment of the app. Task 7's e2e job runs exactly this.

- [ ] **Step 1: `frontend/playwright.alb.config.ts`** (no webServer — the target is remote):

```typescript
import { defineConfig, devices } from "@playwright/test";

// Smoke config for a LIVE deployment (the pipeline's ALB URL, or any
// deployed instance). No webServer: BASE_URL must point at a running app.
//   BASE_URL=http://<alb-host> npm run e2e:alb
export default defineConfig({
  testDir: "./e2e-alb",
  timeout: 60_000, // remote target: generous first-load budget (cold caches)
  retries: 1,
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:5174",
    screenshot: "on", // evidence artifacts, green or red
    // maplibre needs WebGL; software rendering for headless CI Chromium.
    launchOptions: { args: ["--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
```

- [ ] **Step 2: `frontend/e2e-alb/smoke.spec.ts`**

```typescript
import { test, expect } from "@playwright/test";

// Live-deployment smoke: proves the full chain (ALB → web pod → API pods →
// database) serves the real app. Screenshots are the pipeline's evidence.

test("API health answers through the ALB", async ({ request }) => {
  const res = await request.get("/api/v1/health");
  expect(res.status()).toBe(200);
});

test("the app renders the seeded map", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Annotated Maps/i);
  // The persona switcher only renders once the app has data from the API.
  await expect(page.getByText("Viewing as")).toBeVisible({ timeout: 30_000 });
  // The map canvas is up (maplibre creates a canvas element).
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: "test-results/alb-smoke-app.png", fullPage: true });
});

test("personas are present", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Run-club Member" })).toBeVisible({
    timeout: 30_000,
  });
});
```

(Selector guard: `Viewing as` text and the `Run-club Member` persona button exist in the current UI — verify against `frontend/e2e/` specs' existing selectors and reuse their idioms if these differ; the INTENT — app title, data-driven UI rendered, a persona visible, a full-page screenshot — must hold.)

- [ ] **Step 3: `frontend/package.json`** — add to `scripts`: `"e2e:alb": "playwright test --config playwright.alb.config.ts"`.

- [ ] **Step 3b: `frontend/vite.config.ts`** — REQUIRED, or CI fails. vitest's default include glob is `**/*.spec.ts`, so it will collect the new Playwright spec and die with "Playwright Test did not expect test() to be called here." Every Playwright suite dir in this repo is listed in vitest's exclude — follow the convention and add the new one:

```ts
  test: { ..., exclude: ["**/node_modules/**", "e2e/**", "e2e-prod/**", "e2e-alb/**"], ... }
```
- [ ] **Step 4:** Verify. Run **every gate the CI `frontend` job runs** — do NOT assume the existing suites are untouched, PROVE it (a previous run of this plan shipped a red PR by skipping the vitest gate):
  - `cd frontend && npm run lint` → clean
  - `cd frontend && npm run test -- --run` → all files pass, **zero** collected from `e2e-alb/` (this is the gate Step 3b protects)
  - `cd frontend && npm run build` → clean
  - `npx playwright test --config playwright.alb.config.ts --list` → shows the 3 tests
  - REAL verification, needs no AWS: `cd frontend && BASE_URL=https://annotated-maps-web.onrender.com npm run e2e:alb` → all 3 pass.
- [ ] **Step 5:** Commit `feat(e2e): live-deployment smoke suite (BASE_URL-driven) for the pipeline`; push `m4-playwright-alb`; open PR-F.

---

### Task 7 (PR-G): the pipeline + actionlint + ADR-0010 — branch `m4-pipeline-workflow` (REQUIRES B/C/D/E/F merged; branch off updated main)

**Files:**
- Create: `.github/workflows/demo-pipeline.yml`, `docs/adr/0010-pipeline-apply-role.md`
- Modify: `.github/workflows/ci.yml` (infra job += actionlint on both workflows)

**Interfaces:**
- Consumes: make targets (Task 2), `neon-branch.sh` (Task 5), `e2e:alb` (Task 6), role + topic (Tasks 3–4 via repo variables `AWS_DEPLOY_ROLE_ARN`, `SNS_TOPIC_ARN`, `TF_STATE_BUCKET` [exists], `NEON_PROJECT_ID`; secret `NEON_API_KEY`).
- Produces: the dispatchable/scheduled pipeline.

- [ ] **Step 1: `.github/workflows/demo-pipeline.yml`**

```yaml
name: Demo pipeline
# One button: provision → scan-gated images → deploy (per-run Neon branch) →
# e2e vs the live ALB → GUARANTEED destroy. ADR-0010. ~$1-2 and ~35min per run.
on:
  workflow_dispatch:
  schedule:
    - cron: "0 14 3 * *"   # monthly drift check, 3rd @ 14:00 UTC

# Never two runs at once (double spend, state-lock fights); never cancel a
# run that may be mid-teardown.
concurrency:
  group: demo-pipeline
  cancel-in-progress: false

permissions:
  id-token: write
  contents: read
  issues: write

env:
  AWS_REGION: us-east-1

jobs:
  provision:
    runs-on: ubuntu-latest
    environment: aws-deploy
    outputs:
      image_tag: ${{ steps.tag.outputs.tag }}
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.15.8"
          terraform_wrapper: false   # raw terraform output needed by scripts
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: us-east-1
      - name: terraform init (state bucket)
        run: terraform -chdir=deploy/terraform/demo init -input=false
          -backend-config="bucket=${{ vars.TF_STATE_BUCKET }}"
      - name: provision (make demo-infra-up)
        run: make demo-infra-up
      - id: tag
        run: echo "tag=$(git rev-parse --short HEAD)" >> "$GITHUB_OUTPUT"

  images:
    needs: provision
    runs-on: ubuntu-latest
    environment: aws-deploy
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with: { terraform_version: "1.15.8", terraform_wrapper: false }
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: us-east-1
      - name: terraform init (read outputs)
        run: terraform -chdir=deploy/terraform/demo init -input=false
          -backend-config="bucket=${{ vars.TF_STATE_BUCKET }}"
      - name: build images (no push yet)
        run: |
          docker build --platform linux/amd64 -f backend/Dockerfile \
            -t api-candidate:${{ needs.provision.outputs.image_tag }} .
          docker build --platform linux/amd64 -f frontend/Dockerfile \
            -t web-candidate:${{ needs.provision.outputs.image_tag }} frontend
      - name: Trivy gate (CRITICAL, fixable) — api
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: api-candidate:${{ needs.provision.outputs.image_tag }}
          severity: CRITICAL
          ignore-unfixed: true
          exit-code: "1"
          format: json
          output: trivy-api.json
      - name: Trivy gate (CRITICAL, fixable) — web
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: web-candidate:${{ needs.provision.outputs.image_tag }}
          severity: CRITICAL
          ignore-unfixed: true
          exit-code: "1"
          format: json
          output: trivy-web.json
      - name: SBOMs (CycloneDX)
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: api-candidate:${{ needs.provision.outputs.image_tag }}
          format: cyclonedx
          output: sbom-api.cdx.json
      - name: SBOM — web
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: web-candidate:${{ needs.provision.outputs.image_tag }}
          format: cyclonedx
          output: sbom-web.cdx.json
      - name: upload scan + SBOM artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: image-security
          path: |
            trivy-*.json
            sbom-*.cdx.json
      - name: retag + push (gate passed)
        run: |
          ECR_API=$(terraform -chdir=deploy/terraform/demo output -raw ecr_api_url)
          ECR_WEB=$(terraform -chdir=deploy/terraform/demo output -raw ecr_web_url)
          TAG=${{ needs.provision.outputs.image_tag }}
          aws ecr get-login-password --region us-east-1 \
            | docker login --username AWS --password-stdin "${ECR_API%%/*}"
          docker tag "api-candidate:$TAG" "$ECR_API:$TAG"
          docker tag "web-candidate:$TAG" "$ECR_WEB:$TAG"
          docker push "$ECR_API:$TAG"
          docker push "$ECR_WEB:$TAG"

  deploy:
    needs: [provision, images]
    runs-on: ubuntu-latest
    environment: aws-deploy
    outputs:
      alb_url: ${{ steps.appdeploy.outputs.alb_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with: { terraform_version: "1.15.8", terraform_wrapper: false }
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: us-east-1
      - name: terraform init (read outputs)
        run: terraform -chdir=deploy/terraform/demo init -input=false
          -backend-config="bucket=${{ vars.TF_STATE_BUCKET }}"
      - name: create per-run Neon branch
        env:
          NEON_API_KEY: ${{ secrets.NEON_API_KEY }}
          NEON_PROJECT_ID: ${{ vars.NEON_PROJECT_ID }}
        run: ./scripts/neon-branch.sh create "ci-run-${{ github.run_id }}" /tmp/db-url
      - id: appdeploy
        name: deploy + gating smoke (make demo-app-deploy)
        env:
          DB_URL_FILE: /tmp/db-url
          IMAGE_TAG: ${{ needs.provision.outputs.image_tag }}
        run: make demo-app-deploy
      - name: publish demo-ready (severity=info)
        run: |
          aws sns publish --topic-arn "${{ vars.SNS_TOPIC_ARN }}" \
            --subject "demo-ready: annotated-maps pipeline run ${{ github.run_id }}" \
            --message "The ephemeral demo is up at ${{ steps.appdeploy.outputs.alb_url }} (run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }})" \
            --message-attributes '{"severity":{"DataType":"String","StringValue":"info"}}'

  e2e:
    needs: deploy
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: npm ci
        working-directory: frontend
      - run: npx playwright install --with-deps chromium
        working-directory: frontend
      - name: smoke the live ALB
        env:
          BASE_URL: ${{ needs.deploy.outputs.alb_url }}
        run: npm run e2e:alb
        working-directory: frontend
      - name: upload screenshots (evidence, green or red)
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: alb-smoke-screenshots
          path: |
            frontend/test-results/**/*.png

  destroy:
    needs: [provision, images, deploy, e2e]
    if: always() && needs.provision.result != 'skipped'
    runs-on: ubuntu-latest
    environment: aws-deploy
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with: { terraform_version: "1.15.8", terraform_wrapper: false }
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: us-east-1
      - name: terraform init (state bucket)
        run: terraform -chdir=deploy/terraform/demo init -input=false
          -backend-config="bucket=${{ vars.TF_STATE_BUCKET }}"
      - name: install helm + kubectl
        uses: azure/setup-helm@v4
      - name: destroy (make demo-down; re-runnable from any state)
        env:
          NEON_BRANCH: ci-run-${{ github.run_id }}
          NEON_API_KEY: ${{ secrets.NEON_API_KEY }}
          NEON_PROJECT_ID: ${{ vars.NEON_PROJECT_ID }}
        run: make demo-down
      - name: cost line
        run: make demo-cost || true
      - name: publish run-summary (severity=info)
        if: always()
        run: |
          aws sns publish --topic-arn "${{ vars.SNS_TOPIC_ARN }}" \
            --subject "run-summary: annotated-maps pipeline ${{ github.run_id }}" \
            --message "Pipeline run finished. provision=${{ needs.provision.result }} images=${{ needs.images.result }} deploy=${{ needs.deploy.result }} e2e=${{ needs.e2e.result }}. Run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" \
            --message-attributes '{"severity":{"DataType":"String","StringValue":"info"}}'

  alert-teardown-failure:
    needs: destroy
    if: always() && needs.destroy.result == 'failure'
    runs-on: ubuntu-latest
    environment: aws-deploy
    steps:
      - name: open an alarm issue (AWS-independent)
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh issue create --repo "${{ github.repository }}" \
            --title "🔴 TEARDOWN FAILED — billable AWS resources may be running" \
            --body "The demo-pipeline destroy job failed. Billable resources (EKS ~\$0.26/hr) may still be up. Run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }} — re-run \`make demo-down\` locally or re-run the destroy job. See docs/aws-primer.md troubleshooting."
      - uses: aws-actions/configure-aws-credentials@v4
        continue-on-error: true
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: us-east-1
      - name: publish teardown-failed (severity=alert → email)
        continue-on-error: true
        run: |
          aws sns publish --topic-arn "${{ vars.SNS_TOPIC_ARN }}" \
            --subject "ALERT: annotated-maps pipeline teardown FAILED" \
            --message "Destroy failed — billable resources may be running. ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" \
            --message-attributes '{"severity":{"DataType":"String","StringValue":"alert"}}'
```

(Version-pin guard: `aquasecurity/trivy-action@0.28.0` — check the current release at implementation and pin THAT; same intent: scan gate + CycloneDX SBOM. If the action's input names differ in the pinned release, adapt inputs, keep the gate semantics: CRITICAL, `--ignore-unfixed`, exit 1.)

- [ ] **Step 2: actionlint in CI** — in `.github/workflows/ci.yml`'s `infra` job, after the shellcheck step:

```yaml
      - name: actionlint (workflow lint)
        run: |
          curl -fsSL https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_linux_amd64.tar.gz | tar xz actionlint
          ./actionlint .github/workflows/ci.yml .github/workflows/demo-pipeline.yml
```

(Pin the current actionlint release at implementation time; run it LOCALLY too before opening the PR — download the darwin binary or `brew install actionlint` with user authorization.)

- [ ] **Step 3: `docs/adr/0010-pipeline-apply-role.md`** — house style (`# ADR-0010: <title>`, `- Status: accepted`, `- Date: 2026-07-14`, Context/Decision/Consequences/Alternatives considered — mirror ADR-0009). Required content (all from the spec, §1/§2/§5/§7 + brainstorm decisions): the apply-capable role's scoping stance (broad per-service, hard IAM-prefix boundary, state-bucket + one-topic limits); trust = exactly one unprotected-Environment sub, and **the deliberately-omitted reviewer gate** (dispatch requires write access + is fork-unreachable → approval would double-confirm the same human; GitHub approves Environments per-JOB, so any gate touching destroy could hang teardown = stranded billing; the entry-only rule if ever reinstated; `infra-plan` already demonstrates protected Environments where genuine untrusted input exists); SNS lifecycle events + `severity` filter policy (inbox=alerts only, topic carries all; ~$0); KMS-off for the ephemeral cluster (cost vs checkbox); per-run Neon branches (the new secret is a revocable API key, not a DB password); Trivy gate = CRITICAL-with-fix (`--ignore-unfixed`) so an unfixable upstream CVE can't wedge the pipeline. Alternatives: reviewer-gated dispatch, alerts-only SNS, persistent foundation KMS key, static DB secret.

- [ ] **Step 4:** Verify: `actionlint` clean on both workflows; `python3 -c "import yaml; ..."` parses both; every `vars.`/`secrets.` reference is in the Task-8 checkpoint list ({AWS_DEPLOY_ROLE_ARN, TF_STATE_BUCKET, NEON_PROJECT_ID, SNS_TOPIC_ARN} + {NEON_API_KEY}); `make helm-checks`/`obs-checks` untouched-still-green.
- [ ] **Step 5:** Commit `feat(ci): the one-button demo pipeline (dispatch + monthly) + ADR-0010`; push `m4-pipeline-workflow`; open PR-G. **Do not merge yet** — Task 8 iterates live on this branch first.

---

### Task 8: checkpoint + budget-boxed live iteration (CONTROLLER — not subagent work)

**Files:** fixes-as-needed on the `m4-pipeline-workflow` branch, one commit per fix with the failure named.

- [ ] **Step 1 — USER CHECKPOINT (hand over, wait):**
  1. Create a Neon **API key** (console → account → API keys) and run `gh secret set NEON_API_KEY` (paste at the prompt — not into chat).
  2. Confirm PR-C/PR-D are merged.
  3. Tell the agent "checkpoint done."
- [ ] **Step 2 — agent setup:** create the unprotected Environment (`gh api --method PUT repos/dcltdw/annotated-maps-sp/environments/aws-deploy --input - <<< '{}'`); apply the foundation stack (`AWS_PROFILE=... terraform -chdir=deploy/terraform/foundation apply -auto-approve -var budget_alert_email=dcltdw@protonmail.com`) → user clicks the SNS **Confirm subscription** email; set repo variables from outputs: `AWS_DEPLOY_ROLE_ARN`, `SNS_TOPIC_ARN`, `NEON_PROJECT_ID` (from the Neon console URL/API — ask the user if not determinable). `TF_STATE_BUCKET` already exists.
- [ ] **Step 3 — live iteration (money rules: ceiling $10 total, expect 2–4 runs ≈ $1–2 each; never leave a session with infra up — after ANY red run confirm the destroy job swept clean, else run `make demo-down` locally; ledger line per run with `make demo-cost`):** `gh workflow run demo-pipeline.yml --ref m4-pipeline-workflow`, watch with `gh run watch`. Diagnose → fix → commit → dispatch again. Likely first-run issues: deployer-role missing read actions (add-only, never broaden the IAM boundary), Trivy action input drift, Neon API field names, `terraform_wrapper` output quirks.
- [ ] **Step 4 — green from the branch** (all six jobs green, artifacts present, run-summary email NOT received [info-filtered] — verify the message reached the topic via the destroy job's log; teardown swept clean). Then merge PR-G.
- [ ] **Step 5 — the canonical run:** dispatch from `main`; confirm green + artifacts (screenshots, trivy, SBOMs). This run's URL is the roadmap proof. Verify the alert path once WITHOUT stranding anything: `aws sns publish` a test `severity=alert` message (email arrives) and confirm the issue-creation step syntax via a dry `gh issue create --help` check — do NOT force a teardown failure.

---

### Task 9 (PR-H): evidence + docs flip — branch `m4-evidence`

**Files:**
- Create: `docs/m4-pipeline.md`
- Modify: `docs/aws-primer.md` (+§ "The one-button pipeline"), `README.md`, `ROADMAP.md`

- [ ] **Step 1: `docs/m4-pipeline.md`** — the evidence page: date; link to the green **main** run; the job graph (provision→images→deploy→e2e→destroy) with per-job times; the artifacts (embed 1–2 e2e screenshots copied into `docs/img/m4-*.png`, link the Trivy/SBOM artifacts on the run); the cost line; the alert-channel design (issue + filtered SNS email + budget alarm); pointer to ADR-0010.
- [ ] **Step 2: primer §** — how to dispatch (`gh workflow run demo-pipeline.yml` or the Actions UI), what each job does, the monthly schedule, what the SNS filter delivers vs holds, and the teardown-failure runbook (re-run destroy job / `make demo-down` locally / check the sweep).
- [ ] **Step 3: README** — extend the Milestone-3 AWS line: `Milestone 4 wraps the whole lifecycle in a one-button pipeline — see the [pipeline run record](docs/m4-pipeline.md).` **ROADMAP** — Milestone 4 row `📋 Planned` → `✅ Shipped`, Proof = `[pipeline run](docs/m4-pipeline.md) · [workflow](.github/workflows/demo-pipeline.yml) · [ADR-0010](docs/adr/0010-pipeline-apply-role.md)`; "Done means" → past tense with the run link. Add a one-line roadmap footer: all four milestones shipped.
- [ ] **Step 4:** Commit `docs: Milestone 4 evidence — the one-button pipeline run; roadmap complete`; push `m4-evidence`; open PR-H. After merge: board card "Milestone 4" → Done. **The roadmap is complete.**
