# Milestone 3 PR-2 — Live Verification on AWS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. NOTE: this plan is mostly a live-operations protocol run by the CONTROLLER directly (like M1 Task 8 / M2 Task 7) — real terraform applies against a real account are not suitable for fire-and-forget subagents. Task 2 (the foundation-split refactor) IS ordinary code and can be a subagent task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Prove PR-1's environment for real — split foundational identity/budgets into a persistent layer, apply it, budget-box the demo-stack iteration to a green `demo-up`, capture one clean documented up→exercise→destroy run, wire fork-safe plan-on-PR via a protected GitHub Environment, and flip the roadmap.

**Architecture change vs PR-1 (decided 2026-07-09):** PR-1 put the GitHub OIDC provider, CI role, and budgets in the *ephemeral* demo stack — but a PR's `terraform plan` needs the CI role to exist when no demo is running, and the budget alarm should always guard the account. So PR-2 first splits by lifetime: a **persistent foundation stack** (state bucket + OIDC provider + CI role + budgets, applied once, never destroyed) and the **ephemeral demo stack** (VPC/EKS/ECR + the cluster-bound IRSA role). Plan-on-PR is then gated by a **protected GitHub Environment** (`aws-plan`, required reviewer) so fork PRs can't self-assume the role.

**Tech Stack:** everything from PR-1, plus `aws-actions/configure-aws-credentials` (OIDC) + a protected GitHub Environment.

**Spec:** `docs/superpowers/specs/2026-07-09-aws-infra-milestone-design.md` §5–§7, §10–§11. **Prerequisite: PR-1 (#47) merged** (verify `deploy/terraform/demo/eks.tf` exists on main — STOP if not).

## Global Constraints (the money rules — bind every task)

- Hard ceiling **$15** total spend; budget alarm at **$10**. At the ceiling: demo-down, stop, regroup with the user.
- **Never end a work session with billable infra up.** Any failure → `make demo-down` before stopping. demo-down is re-runnable from any state.
- Report each apply/destroy cycle: what changed, what broke, `make demo-cost` reading.
- Blanket apply/destroy authorization within the ceiling was given by the user (2026-07-09) — do not re-ask per run.
- Secrets (Neon URL, SSO profile) live at runtime prompts / local AWS config only — never committed, never echoed.
- Repo conventions: `Co-Authored-By` trailer; rigor-section PR body.

---

### Task 1: USER CHECKPOINT — account, identity, Neon branch (STOP; user actions)

**Files:** none. Hand the user this checklist and wait:

- [ ] 1. Create a fresh AWS account (unique email alias works). Sign in as root, enable **MFA on root**, note the account email (it receives the budget alerts).
- [ ] 2. Enable **IAM Identity Center** (us-east-1): create a permission set (`AdministratorAccess` is fine for a solo demo account), a user for yourself, assign both. Locally: `aws configure sso` (profile suggestion `annotated-maps-demo`), then `aws sso login --profile annotated-maps-demo`.
- [ ] 3. In Neon: create a branch of the demo database named `aws-demo`; the connection string goes into demo-up's prompt at runtime, NOT into chat.
- [ ] 4. Tell the agent: "checkpoint done", the SSO **profile name**, and the **budget email**.

Agent then verifies + creates the protected Environment (agent actions once the checkpoint is done):
```bash
AWS_PROFILE=annotated-maps-demo aws sts get-caller-identity   # expect the new account id
UID=$(gh api users/dcltdw --jq .id)
gh api -X PUT repos/dcltdw/annotated-maps-sp/environments/aws-plan \
  -f "reviewers[][type]=User" -F "reviewers[][id]=$UID"       # required-reviewer gate
```
Export `AWS_PROFILE` for the rest of the plan.

---

### Task 2: Foundation-split refactor (code — subagent-eligible)

Move the account-level, must-outlive-a-demo resources into a persistent stack. **No AWS calls in this task — static-verified like PR-1.**

**Files:**
- Create: `deploy/terraform/foundation/` = the existing `bootstrap/main.tf` (state bucket) PLUS the moved `iam-ci.tf` + `budgets.tf` + a `versions.tf`/`providers.tf`/`variables.tf` (region, budget_alert_email) + `outputs.tf` (state_bucket, ci_role_arn). (Renaming `bootstrap/` → `foundation/` is cleanest; keep local state there — it now holds the CI role + budgets too, all persistent.)
- Delete from `deploy/terraform/demo/`: `iam-ci.tf`, `budgets.tf`; remove `ci_role_arn` from `demo/outputs.tf` and `budget_alert_email` from `demo/variables.tf` (it moves to foundation).
- Modify: `demo/iam-irsa.tf` stays (cluster-bound, ephemeral). `.github/workflows/ci.yml` infra job's validate/tflint steps must now also cover `deploy/terraform/foundation/`.

**Interfaces:**
- Produces: foundation outputs `state_bucket`, `ci_role_arn`. demo stack no longer creates the CI role/OIDC provider/budgets.

- [ ] **Step 1:** Restructure per the file list. The CI role trust policy's `:sub` changes from the main-ref value to the **Environment** sub (StringEquals):
  ```hcl
  values = ["repo:dcltdw/annotated-maps-sp:environment:aws-plan"]
  ```
  with a comment: only a job that declares `environment: aws-plan` gets this sub, and that Environment has a required-reviewer rule, so fork PRs pause for human approval before any token is issued — fork-safe while keeping plan-on-PR. Keep the read-only permission policy unchanged.
- [ ] **Step 2:** The demo stack still references the cluster OIDC provider for IRSA (unchanged). Confirm no dangling references (demo no longer outputs ci_role_arn; nothing in demo consumed budgets).
- [ ] **Step 3:** Static gate (both stacks): `terraform fmt -check -recursive deploy/terraform`; `foundation` + `demo` each `init -backend=false && validate`; `tflint` both; update + run the CI `infra` job locally. Commit.
- [ ] **Step 4:** Update `docs/aws-primer.md` + `docs/adr/0009` to describe the persistent-foundation / ephemeral-demo split and the Environment-gated plan-on-PR (supersede the PR-1 "intended for PR-2" note).

---

### Task 3: Apply the foundation FIRST (persistent; budgets before any demo spend)

- [ ] **Step 1:** `terraform -chdir=deploy/terraform/foundation init && terraform -chdir=deploy/terraform/foundation apply -auto-approve -var budget_alert_email=<EMAIL>`. This creates the state bucket, the GitHub OIDC provider, the CI role, and the **budget alarm** — all persistent. Note `state_bucket` + `ci_role_arn` outputs.
- [ ] **Step 2:** Init the demo backend against the real bucket: `terraform -chdir=deploy/terraform/demo init -backend-config="bucket=<state_bucket>"`.
- [ ] **Step 3:** User confirms the AWS Budgets confirmation email arrived. **No EKS spend may exist before this box is checked** (the alarm is now live and persistent).

---

### Task 4: Budget-boxed iteration to a green demo-up (controller)

- [ ] **Step 1:** `make demo-up` (watch, don't background-and-forget: EKS apply ~15–20 min). On failure: diagnose → **`make demo-down`** → fix → commit → next cycle. Likely first-cycle issues (primer): IAM propagation, ALB-controller webhook timing, ECR auth, image platform, and possibly a few extra read-only actions the plan/apply needs (add-only, never a security relaxation).
- [ ] **Step 2:** After each cycle: `make demo-cost`; ledger line (`cycle N: <what broke> — $X.XX MTD`).
- [ ] **Step 3:** "Green" = demo-up completes unattended through its own smoke (health 200 + doctype on the ALB URL) AND a following `make demo-down` sweeps to empty. Do not proceed until one full up→down cycle is clean end-to-end.

---

### Task 5: The documented run — evidence bundle (controller)

**Files:** `docs/img/m3-*.png` (indicative names), `docs/m3-demo-run.md`.

- [ ] **Step 1:** `make demo-up` (clean run). Exercise: open `http://<ALB>/` headlessly (Playwright), confirm the seeded Boston app renders through the ALB; `python3 scripts/synthetic_traffic.py --base-url http://<ALB> --loops 20`; screenshot the app, `kubectl get pods -A`, and the EKS console.
- [ ] **Step 2:** `make demo-down`. Capture: destroy completing, the post-destroy sweep (all-empty), `make demo-cost` (the receipt).
- [ ] **Step 3:** Write `docs/m3-demo-run.md` (date, timeline, images, cost receipt, runbook pointer). This page + images = the ROADMAP proof.
- [ ] **Step 4:** Commit the bundle.

---

### Task 6: Fork-safe plan-on-PR via the protected Environment + ruleset + roadmap flip

**Files:** `.github/workflows/ci.yml` (infra job += Environment-gated OIDC plan), `README.md`, `ROADMAP.md`.

- [ ] **Step 1:** `gh variable set AWS_CI_ROLE_ARN --body "<foundation ci_role_arn>"` and `gh variable set TF_STATE_BUCKET --body "<state_bucket>"`. In ci.yml, add a step-set to the `infra` job that runs on PRs, declares the Environment (so its OIDC sub is `...:environment:aws-plan`), and plans read-only:
  ```yaml
      - name: OIDC plan (Environment-gated; fork PRs pause for approval)
        if: github.event_name == 'pull_request'
        environment: aws-plan
        permissions: { id-token: write, contents: read }
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_CI_ROLE_ARN }}
          aws-region: us-east-1
      - name: terraform plan (read-only role, no state lock write)
        if: github.event_name == 'pull_request'
        run: |
          terraform -chdir=deploy/terraform/demo init \
            -backend-config="bucket=${{ vars.TF_STATE_BUCKET }}"
          # -lock=false: the CI role is READ-ONLY (no PutObject), so it can't
          # write the native S3 .tflock; a read-only plan doesn't need the lock.
          terraform -chdir=deploy/terraform/demo plan -input=false -lock=false \
            -var budget_alert_email=ci-plan-placeholder@example.com
  ```
  (`environment:` is a JOB-level key in real YAML — if the OIDC+plan steps need to share the Environment, put them in a dedicated `infra-plan` job with `environment: aws-plan` at job level, `if: github.event_name == 'pull_request'`, rather than as step keys. Implement whichever the actions schema requires; the intent is: the plan runs in the `aws-plan` Environment on PRs.)
- [ ] **Step 2:** Verify fork-safety on a real PR: open a trivial PR → the `aws-plan` job **pauses for your approval** → approve (after eyeballing the PR's workflow diff is benign) → the plan runs and posts (expected: "creates" — the demo is destroyed between runs; proves read works). A fork PR would pause identically and never get a token without approval. Capture this in the evidence.
- [ ] **Step 3:** Add `infra` to the main ruleset's required checks (ruleset id 17463753, integration_id 15368 — the M1 API pattern). NOTE: the Environment-gated plan step is `pull_request`-only and requires your approval, so don't make the WHOLE infra job required if that would block merges on unapproved plans — make the static portion required and keep the plan step non-blocking (or a separate non-required job). Decide at implementation.
- [ ] **Step 4:** README: extend the M3 pointer with the evidence-page link. ROADMAP: Milestone 3 row `📋 Planned` → `✅ Shipped`; Proof → `[demo run](docs/m3-demo-run.md) · [terraform](deploy/terraform/) · [ADR-0009](docs/adr/0009-eks-over-ecs.md) · [primer](docs/aws-primer.md)`; "Done means" → past tense.
- [ ] **Step 5:** Commit; open the PR (rigor sections). After merge: board card "Milestone 3" → Done; confirm no infra is up (`make demo-cost` + sweep). NOTE: the persistent foundation stack (state bucket + CI role + budget) stays up by design — it's free (S3 pennies + a $0 budget) and must persist for CI plans; only the demo compute is torn down.
