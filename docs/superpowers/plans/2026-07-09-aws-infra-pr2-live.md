# Milestone 3 PR-2 — Live Verification on AWS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. NOTE: this plan is mostly a live-operations protocol run by the CONTROLLER directly (like M1 Task 8 / M2 Task 7) — real terraform applies against a real account are not suitable for fire-and-forget subagents. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Prove PR-1's environment for real — budgets first, budget-boxed iteration to a green `demo-up`, one clean documented up→exercise→destroy run with evidence, plan-in-CI via OIDC, roadmap flip.

**Architecture:** No new design — this plan executes PR-1's code against the fresh AWS account created at the user checkpoint, fixes what reality disagrees with, and captures the proof.

**Tech Stack:** Everything from PR-1, plus `aws-actions/configure-aws-credentials` (OIDC) in CI.

**Spec:** `docs/superpowers/specs/2026-07-09-aws-infra-milestone-design.md` §5–§7, §10–§11. **Prerequisite: PR-1 merged** (verify `deploy/terraform/demo/eks.tf` exists on main — STOP if not).

## Global Constraints (the money rules — bind every task)

- Hard ceiling **$15** total spend; budget alarm at **$10**. At the ceiling: demo-down, stop, regroup with the user.
- **Never end a work session with billable infra up.** Any failure → `make demo-down` before stopping. demo-down is re-runnable from any state.
- Report each apply/destroy cycle: what changed, what broke, `make demo-cost` reading.
- Blanket apply/destroy authorization within the ceiling was given by the user (2026-07-09) — do not re-ask per run.
- Secrets (Neon URL, SSO profile) live at runtime prompts / local AWS config only — never committed, never echoed into logs or chat.
- Repo conventions: `Co-Authored-By` trailer; rigor-section PR body.

---

### Task 1: USER CHECKPOINT — account, identity, Neon branch (STOP; user actions)

**Files:** none. Hand the user this checklist and wait:

- [ ] 1. Create a fresh AWS account (unique email alias works). Sign in as root, enable **MFA on root**, note the account email (it receives the budget alerts).
- [ ] 2. Enable **IAM Identity Center** (in us-east-1): create a permission set (`AdministratorAccess` is fine for a solo demo account), a user for yourself, and assign both to the account.
- [ ] 3. Locally: `aws configure sso` (SSO start URL + region from the Identity Center console; profile name suggestion: `annotated-maps-demo`), then `aws sso login --profile annotated-maps-demo`.
- [ ] 4. In Neon: create a branch of the demo database named `aws-demo` and copy its connection string (you'll paste it into demo-up's prompt at runtime, NOT into chat).
- [ ] 5. Tell the agent: "checkpoint done", the SSO **profile name**, and the **budget email** to use.

Agent verification that the gate passed:
```bash
AWS_PROFILE=annotated-maps-demo aws sts get-caller-identity
```
Expected: JSON with the new account id. Export `AWS_PROFILE` for the rest of the plan.

---

### Task 2: Bootstrap state + budgets FIRST (controller)

**Files:** none new (PR-1 code). Possibly a `deploy/terraform/demo/` fix commit if reality disagrees.

- [ ] **Step 1:** Apply the bootstrap stack (local state):
```bash
terraform -chdir=deploy/terraform/bootstrap init
terraform -chdir=deploy/terraform/bootstrap apply -auto-approve
# note the state_bucket output
```
- [ ] **Step 2:** Init the demo backend against the real bucket:
```bash
terraform -chdir=deploy/terraform/demo init \
  -backend-config="bucket=annotated-maps-tf-state-<ACCOUNT_ID>"
```
- [ ] **Step 3:** Budgets BEFORE any compute exists:
```bash
terraform -chdir=deploy/terraform/demo apply -auto-approve \
  -target=aws_budgets_budget.demo -var budget_alert_email=<EMAIL>
```
(`-var` at every demo apply from here on, or export `TF_VAR_budget_alert_email`.) User confirms the AWS Budgets subscription/confirmation email arrived. **No EKS spend may exist before this box is checked.**

---

### Task 3: Budget-boxed iteration to a green demo-up (controller)

**Files:** whatever reality requires — each fix is a small commit on the PR-2 branch with the failure named in the message.

- [ ] **Step 1:** First full cycle: `make demo-up` (watch, don't background-and-forget: apply ~15–20 min for EKS). On failure: diagnose, **`make demo-down`**, fix, commit, next cycle. Known-likely first-cycle issues (primer troubleshooting): IAM propagation, ALB controller webhook timing, ECR auth, image platform.
- [ ] **Step 2:** After each cycle: `make demo-cost`; append one line to the ledger (`cycle N: <what broke> — $X.XX month-to-date`).
- [ ] **Step 3:** Success criteria for "green": demo-up completes unattended through its own smoke (health 200 + doctype on the ALB URL), and `make demo-down` afterward sweeps to empty. Do NOT proceed to Task 4 until a full up→down cycle is clean end-to-end.

---

### Task 4: The documented run — evidence bundle (controller)

**Files:**
- Create: `docs/img/m3-app-on-alb.png`, `docs/img/m3-eks-pods.png`, `docs/img/m3-destroy-zero.png` (names indicative — keep them descriptive)
- Create: `docs/m3-demo-run.md` (the evidence page)

- [ ] **Step 1:** `make demo-up` (the clean run). Exercise: open `http://<ALB>/` headlessly (Playwright, as in M1/M2), confirm the seeded Boston app renders through the ALB; run `python3 scripts/synthetic_traffic.py --base-url http://<ALB> --loops 20`; screenshot the app, `kubectl get pods -A` output, and the EKS console cluster page.
- [ ] **Step 2:** `make demo-down`. Screenshot/capture: destroy completing, the post-destroy sweep (all-empty), and `make demo-cost` (the receipt).
- [ ] **Step 3:** Write `docs/m3-demo-run.md`: date, what ran, the timeline (up N min, exercised, down M min), the images, the cost receipt, and a pointer to the primer's runbook. This page + images are the ROADMAP proof.
- [ ] **Step 4:** Commit the bundle.

```bash
git add docs/img/m3-*.png docs/m3-demo-run.md
git commit -m "docs: Milestone 3 live-run evidence — up, exercised, destroyed to zero"
```

---

### Task 5: plan-in-CI (OIDC), ruleset, roadmap flip

**Files:**
- Modify: `.github/workflows/ci.yml` (infra job += OIDC plan step), `README.md`, `ROADMAP.md`

**SECURITY NOTE (from Task 3's review):** the CI role's trust policy is pinned to `repo:dcltdw/annotated-maps-sp:ref:refs/heads/main` — **push to our main only**, NOT `pull_request`. This is deliberate: on a public repo, a `pull_request`-triggered OIDC job is assumable by fork PRs (GitHub sets the same base-repo `:pull_request` sub for forks). So the OIDC `terraform plan` runs **on push to main**, not on PRs. The static checks (fmt/validate/tflint/shellcheck) still run on every PR — the roadmap's "validate/lint on every infra PR" holds; the authenticated plan is the merge-to-main gate. (If plan-on-PR is ever wanted, the secure way is a protected GitHub Environment whose sub is `...:environment:NAME` + a trust-policy entry for it — a deliberate future addition, not bare `pull_request`.)

- [ ] **Step 1:** Set the repo variables: `gh variable set AWS_CI_ROLE_ARN --body "<ci_role_arn output>"` and `gh variable set TF_STATE_BUCKET --body "annotated-maps-tf-state-<ACCOUNT_ID>"`. In ci.yml, give the `infra` job `permissions: { id-token: write, contents: read }` and append (after tflint/shellcheck) — the OIDC + plan steps gated to **push-to-main** so they match the trust policy and never run for PRs/forks:

```yaml
      - name: OIDC auth (push-to-main only; no long-lived keys)
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_CI_ROLE_ARN }}
          aws-region: us-east-1
      - name: terraform plan (read-only role)
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        run: |
          terraform -chdir=deploy/terraform/demo init \
            -backend-config="bucket=${{ vars.TF_STATE_BUCKET }}"
          # -lock=false: the CI role is READ-ONLY (GetObject/ListBucket on the
          # state bucket, no PutObject). The native S3 lock writes a .tflock
          # object, which the role deliberately can't do — a read-only plan
          # doesn't need the lock. Without this flag the plan fails AccessDenied
          # acquiring the lock. (Found by the PR-1 final review.)
          terraform -chdir=deploy/terraform/demo plan -input=false -lock=false \
            -var budget_alert_email=ci-plan-placeholder@example.com
```

Verify on the post-merge main run (not the PR run): the OIDC step assumes `annotated-maps-ci` and plan succeeds (expected plan: creates — the env is destroyed between runs; that's correct and proves read works). NOTE: the budget-email placeholder is fine for plan (no apply ever happens in CI). Because plan runs only on main, the PR that adds this step won't exercise it on its own PR run — confirm on the merge run and capture it in the evidence.
- [ ] **Step 2:** Add `infra` to the main ruleset's required checks (the ruleset API pattern from the M1 session — ruleset id 17463753, integration_id 15368).
- [ ] **Step 3:** README: extend the M3 pointer line with the evidence page link. ROADMAP: Milestone 3 row `📋 Planned` → `✅ Shipped`, Proof cell → `[demo run](docs/m3-demo-run.md) · [terraform](deploy/terraform/) · [ADR-0009](docs/adr/0009-eks-over-ecs.md) · [primer](docs/aws-primer.md)`; the milestone body's "Done means" → past tense with the same links.
- [ ] **Step 4:** Commit; open the PR (rigor sections). After merge: board card "Milestone 3" → Done; confirm no infra is up (`make demo-cost` + the sweep one last time).
