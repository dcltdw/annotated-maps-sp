# Milestone 4 — One-Button Ephemeral Environment — Design

- **Date:** 2026-07-14
- **Status:** Approved design, pending implementation plans
- **Slice:** Roadmap Milestone 4 (board card "Milestone 4 — One-button ephemeral environment") — the capstone
- **Roadmap contract (ROADMAP.md):** a green public run visible in the Actions
  history, with test screenshots attached as artifacts; the destroy step
  guaranteed to run even when a prior step fails.

## Context

Milestone 3 proved the up→exercise→down cycle by hand: `make demo-up`
provisioned EKS behind an ALB, the app served, `make demo-down` swept to zero
(docs/m3-demo-run.md). Milestone 4 automates that exact cycle as **one
`workflow_dispatch` GitHub Actions pipeline** — provision → build/scan/push →
deploy → test → guaranteed destroy — plus an unattended monthly run for drift
detection. It spends real money per run (~$1–2) and grants CI an
apply-capable AWS role, so cost guardrails and the apply-role security model
are first-class design elements, not afterthoughts.

Decisions locked during brainstorming:

1. **Per-run Neon branch via API** — each run creates a fresh database branch,
   uses it, deletes it in teardown. `NEON_API_KEY` is the one new GitHub
   Actions secret; a connection string exists only inside a run.
2. **Approval gate + unattended monthly:** manual dispatches are admitted
   through a reviewer-gated `aws-deploy` Environment; the monthly cron enters
   unattended through `aws-deploy-scheduled` (no reviewer, main-branch-only).
   The gate sits at ENTRY only — downstream jobs, including destroy, never
   wait on a human (§2).
3. **Pipeline structure:** phased make targets shared by laptop and CI
   (`demo-infra-up` / `demo-images` / `demo-app-deploy` / `demo-down`); the
   workflow's jobs mirror the phases 1:1. One orchestration code path.
4. **KMS:** stop creating a per-cluster CMK (`create_kms_key = false`) — ends
   the ~$1/mo pending-deletion accrual per run; recorded honestly in ADR-0010.
5. **Teardown-failure alerting is triple-channel:** auto-created GitHub issue
   (GITHUB_TOKEN, AWS-independent) + **SNS email to dcltdw@protonmail.com**
   (foundation-stack topic, published from the destroy job's OIDC session) +
   the existing $10 budget alarm as the slow money backstop.
6. The three M3 hardening tickets fold in: smoke **hard-fails**, secrets via
   `--set-file` (never command-line args), `demo-cost` degrades gracefully
   when Cost Explorer isn't ingested.

## Goals

1. One button: a maintainer dispatches the pipeline, approves the
   `aws-deploy` deployment once, and ~35 minutes later has a green public run
   proving the full lifecycle — with screenshots, a Trivy report, and an SBOM
   as downloadable artifacts.
2. A red run cannot strand billable resources silently: destroy always runs,
   is re-runnable from any state, and its own failure triggers three
   independent alarms.
3. The apply-capable role is scoped to this stack and reachable only through
   the three Environments of §2 — no long-lived keys, fork-unreachable
   triggers, and teardown never waits on a human.
4. Monthly unattended run catches dependency/tool/base-image/API drift.
5. ADR-0010 records the security and cost decisions.

## Non-goals (named)

- **No deploy-on-merge / continuous deployment** — the pipeline is a
  demonstration lifecycle, not a delivery pipeline; the always-on demo stays
  on Render.
- **No multi-environment matrix, no promotion flow** — one ephemeral env.
- **No Trivy gate on the always-on Render path** — scan gates apply to this
  pipeline's images; wiring scanning into the Render deploy is out of scope.
- **No PagerDuty/Slack** — email + GitHub issue are the alert surfaces.
- **The read-only `annotated-maps-ci` role and the `infra-plan` job are
  untouched.**

## Design

### 1. The deployer role (`foundation/iam-deployer.tf`, hand-written)

A second role, `annotated-maps-deployer`, apply-capable. Scoping stance
(ADR-0010): `terraform apply` of the demo stack legitimately requires broad
service powers, so the policy grants full `ec2:*`, `eks:*`, `ecr:*`,
`elasticloadbalancing:*`, `logs:*`, `autoscaling:*`, plus KMS/describe reads —
but is **bounded where it counts**:

- **S3:** read-write on the state bucket only (`annotated-maps-tf-state-*`).
- **IAM:** all `iam:*` actions restricted to resources matching
  `annotated-maps-*` (role names, policies, instance profiles, OIDC provider
  read), and `iam:PassRole` scoped the same — it manages the stack's own
  roles and can't mint or touch anything else in the account. The EKS
  module's node-group service roles fit the prefix (verified at
  implementation; rename via module inputs if any default name doesn't).
- **SNS:** `sns:Publish` on the alerts topic ARN only (§5).

Trust policy: `sts:AssumeRoleWithWebIdentity` from the GitHub OIDC provider,
`aud = sts.amazonaws.com`, and `sub` StringEquals **exactly three values** —
the three Environments of §2:
`repo:dcltdw/annotated-maps-sp:environment:aws-deploy`,
`repo:dcltdw/annotated-maps-sp:environment:aws-deploy-scheduled`, and
`repo:dcltdw/annotated-maps-sp:environment:aws-deploy-auto`.

### 2. The Environments (gate model — ADR-0010's core)

**Approve at entry, never downstream — the load-bearing rule.** GitHub
requests Environment approval per *job*, and a job that starts later in a run
can raise a fresh approval request. If the destroy job sat behind a
required-reviewer Environment, a teardown could hang waiting for a human
click — the exact stranded-billing failure this milestone exists to prevent.
So the reviewer gate applies to the **first AWS job only** (provision =
where spend begins); every downstream job — including destroy — uses a
no-reviewer Environment and proceeds unattended once the run was admitted.

| Environment | Protection | Used by | The gate is |
|---|---|---|---|
| `aws-deploy` | required reviewer (dcltdw) | **provision** job of `workflow_dispatch` runs | **money** — no manual run starts spending without a human click |
| `aws-deploy-scheduled` | no reviewer; deployment branch policy = `main` only | **provision** job of the monthly `schedule` run | **code** — unattended runs execute only reviewed, merged main |
| `aws-deploy-auto` | no reviewer | all downstream AWS jobs (images/deploy/destroy) of every run | **entry** — reachable only after a run was admitted above |

Why the no-reviewer surfaces are safe: `workflow_dispatch` and `schedule`
events cannot be triggered by forks and require write access to dispatch —
the threat model here is accidental/runaway spend and unreviewed code, not
strangers (that's the `infra-plan`/PR story, unchanged). `aws-deploy-auto`
grants nothing a maintainer doesn't already effectively hold via dispatch;
its purpose is exclusively to keep teardown human-independent. The provision
job selects its Environment dynamically:
`environment: ${{ github.event_name == 'schedule' &&
'aws-deploy-scheduled' || 'aws-deploy' }}`. (If implementation verifies that
GitHub auto-approves later same-run jobs on an approved environment, the
design still stands — gate-at-entry is correct under either behavior.)

Cost posture: manual runs ≈ $1–2 each, approved individually; scheduled = 12
runs/yr ≈ $15–25/yr; the $10/mo budget alarm already covers both.

### 3. The pipeline (`.github/workflows/demo-pipeline.yml`)

Triggers: `workflow_dispatch` (with a branch selector — used to iterate on
the PR branch) + `schedule` (monthly, e.g. `0 14 3 * *`). A `concurrency`
group (`demo-pipeline`, `cancel-in-progress: false`) forbids overlapping runs
— double spend and state-lock fights — and never cancels a run that may be
mid-teardown.

Jobs (each AWS-touching job authenticates itself via OIDC + the Environment;
terraform outputs travel as job outputs):

1. **provision** — `make demo-infra-up`: terraform init (state bucket) +
   apply. Outputs: cluster name, region, ECR URLs.
2. **images** — `make demo-images`: build both images (`--platform
   linux/amd64`, git-SHA tag), **Trivy scan** (gate: fail on CRITICAL; full
   report uploaded as an artifact), **SBOM** generated (`trivy sbom`,
   CycloneDX) and uploaded, push to ECR. Needs provision's outputs (ECR).
3. **deploy** — create Neon branch `ci-run-<run_id>` (Neon API; §4), then
   `make demo-app-deploy`: kubeconfig, ALB controller, helm install with
   `--set-file` secrets, wait for ALB, **smoke that hard-fails** (health 200
   + doctype within the window or exit 1). Output: the ALB URL.
4. **e2e** — Playwright against `BASE_URL=http://<ALB>` (a small
   `playwright.alb.config.ts` reading `BASE_URL` from env; a smoke-scoped
   spec: app loads, personas render, API answers). **Screenshots uploaded
   `if: always()`** — evidence on green, diagnosis on red.
5. **destroy** — **`if: always()`**, own OIDC auth: `make demo-down`
   (uninstall → wait-ALB-gone → terraform destroy → sweep), delete the Neon
   branch (tolerate already-gone), print `make demo-cost`. This is the same
   re-runnable-from-any-state script M3 proved.
6. **alert-teardown-failure** — runs only if destroy failed: creates a
   GitHub issue titled "🔴 TEARDOWN FAILED — billable AWS resources may be
   running" (run URL + sweep output; via GITHUB_TOKEN, AWS-independent) AND
   publishes the same message to the SNS topic → **email to
   dcltdw@protonmail.com** (via the destroy job's role if AWS auth works; the
   issue fires regardless). Backstop: the $10 budget alarm.

### 4. Per-run Neon branch

Secrets/vars: `NEON_API_KEY` (Actions secret — the one new secret;
API-scoped, revocable, not a DB password), `NEON_PROJECT_ID` (variable). A
small `scripts/neon-branch.sh` (`create <name>` / `delete <name>`) wraps the
Neon API: create from the project's default branch (fresh copy of schema +
seed... the migrate hook re-migrates and reseeds anyway per `values-demo`),
poll until ready, emit the connection string rewritten `postgresql://` →
`postgis://` **to a file** — consumed by `demo-app-deploy` via `--set-file`,
never an argument, never logged (`set +x` discipline; the key travels only in
an env var to curl). Teardown deletes the branch by name; deleting a
nonexistent branch is a warning, not a failure. Local flow (prompt /
`DB_URL_FILE` / the `aws-demo` branch) is untouched.

### 5. Foundation additions

- `foundation/sns.tf`: topic `annotated-maps-alerts` + email subscription
  `dcltdw@protonmail.com` (one-time "Confirm subscription" click at the
  checkpoint). Output: topic ARN. The budget alarm stays as-is.
- `foundation/iam-deployer.tf` (§1). Outputs: `deployer_role_arn`.
- Applied once at the checkpoint (a `terraform apply` on foundation — tags
  already say persistent).

### 6. Make-target refactor (one code path)

`scripts/demo-up.sh` splits into `scripts/demo-infra-up.sh`,
`scripts/demo-images.sh`, `scripts/demo-app-deploy.sh` (each a make target;
`make demo-up` chains all three so the local flow is byte-for-byte the same
experience). `demo-down.sh` unchanged in role (gains the Neon-branch delete
only when a branch name is supplied via env — local runs don't pass one).
Hardening lands here: the smoke in `demo-app-deploy.sh` **exits 1** if health
never returns 200 in the window (no more unconditional "Demo is UP");
secrets flow via `--set-file`; `demo-cost.sh` catches
`DataUnavailableException` and prints the resource-hour estimate note
instead of erroring. All shellcheck'd; CI's shellcheck step covers the new
files.

### 7. EKS change

`create_kms_key = false` + `cluster_encryption_config = {}` in
`demo/eks.tf` (exact input names verified against the pinned module major at
implementation). Effect: no per-run customer-managed KMS key, no ~$1/mo
pending-deletion tail per cycle. ADR-0010 records why that's the right cost
call for a zero-sensitive-data, hours-long demo (control-plane storage is
AWS-encrypted regardless; the CMK only adds envelope encryption for etcd
secrets). The one existing pending-deletion key from M3 expires on its own.

### 8. Verification matrix

- **Static (PR-1, no AWS):** shellcheck (all demo scripts incl. new),
  terraform fmt/validate/tflint (foundation incl. new files + demo),
  `actionlint` on the workflows (new — added to the `infra` CI job),
  helm-checks/obs-checks unchanged and still green, workflow YAML parses.
- **Live (budget-boxed, M3 rules):** iterate via `workflow_dispatch` from the
  PR branch (each run individually approved through `aws-deploy`): expect
  2–4 runs at ~$1–2; **ceiling $10**, never-leave-up (the destroy job is the
  rule; manual sweep after any red run), per-run cost line in the ledger.
- **The proof:** after merge, **one green run from `main`** — public in the
  Actions history with screenshots/Trivy/SBOM artifacts — is the roadmap's
  "done means." Then the monthly cron is live. Teardown-alerting is verified
  once by forcing the alert path (publish a test SNS message + a dry-run of
  the issue step), not by deliberately stranding a cluster.

### 9. ADR-0010 — an apply-capable role for the pipeline

House style. Content: the two-Environment gate model (money-gate vs
code-gate; why dispatch/schedule triggers change the threat model vs PRs);
the deployer-role scoping stance (broad service powers, hard boundary at
IAM-by-prefix + state-bucket + one SNS topic); KMS-off-by-default for the
ephemeral cluster (cost vs a checkbox); per-run Neon branches (the one new
secret is an API key, not a database credential). Alternatives considered:
single reviewer-gated environment (blocks unattended monthly), no gate
(dispatch-only, weaker money story), persistent KMS key in foundation
(+$12/yr for a checkbox).

### 10. Docs

- `docs/aws-primer.md`: new §"The one-button pipeline" (jobs, gates, how to
  dispatch, what the artifacts are, the teardown-alarm channels).
- `docs/m4-pipeline.md` (PR-2): the evidence page — link to the green public
  run, artifact screenshots inline, cost line, pointer to ADR-0010.
- README + ROADMAP flip in PR-2 (roadmap row → ✅ with proof links; this
  completes the roadmap — all milestones shipped).

### 11. User checkpoint (between PR-1 and the live iteration)

1. Create a **Neon API key** (Neon console → account settings → API keys) →
   `gh secret set NEON_API_KEY`; agent sets `NEON_PROJECT_ID` variable.
2. Agent creates the three GitHub Environments (`aws-deploy` w/ required
   reviewer; `aws-deploy-scheduled` w/ main-only branch policy;
   `aws-deploy-auto` unprotected) and applies the foundation additions
   (deployer role + SNS topic).
3. You click the SNS **"Confirm subscription"** email once.
4. Live iteration begins: you approve each `aws-deploy` deployment as runs
   are dispatched.

### 12. PR slicing

- **PR-1 (static):** foundation deployer-role + SNS TF, the workflow, the
  make/script refactor + hardening, Neon script, eks.tf KMS change,
  Playwright ALB config, actionlint in CI, ADR-0010, primer section. All
  CI-green with zero live runs.
- **Checkpoint** (§11), then budget-boxed live iteration to a green
  branch-dispatched run.
- **PR-2 (evidence):** m4-pipeline.md + README/ROADMAP flip; after merge, the
  canonical green run from main + board card → Done. **Roadmap complete.**

## Risks & mitigations

- **Unattended scheduled run fails teardown** — the whole design centers on
  this: destroy `if: always()` + re-runnable-from-any-state + issue + SNS
  email + budget alarm. Residual risk is bounded to hours at ~$0.26/hr.
- **Trivy gate blocks on an upstream CVE** (base image CRITICAL with no fix)
  — gate on CRITICAL-with-fix-available (`--ignore-unfixed`); the full
  report artifact still shows everything. Recorded in ADR-0010.
- **Concurrency**: the `concurrency` group serializes runs; the scheduled
  run simply queues if a manual run is active.
- **Neon API drift/limits** — branch create/delete are core API calls;
  deletion tolerance + the branch is free-tier and empty-cost if orphaned
  (a leftover branch costs storage pennies, not compute).
- **Environment-selection bug routing scheduled runs to the reviewer-gated
  env** — worst case is a hung (not billing) run: the gate sits at entry,
  before any spend exists; the expression is unit-visible in the workflow
  and exercised in the first month's run.

## Testing summary

Static: shellcheck + terraform gates + actionlint + helm/obs-checks (PR-1).
Live: budget-boxed branch dispatches (≤$10) → merge → one green public run
from main with artifacts (the roadmap proof) → monthly cron live. Alert path
verified by forced test message, not a stranded cluster.
