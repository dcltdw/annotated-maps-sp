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
2. **No approval clicks + unattended monthly (revised 2026-07-14 at user
   review):** dispatching IS the confirmation — `workflow_dispatch` requires
   write access and is fork-unreachable, so a reviewer gate would be a second
   confirmation by the same person. No job ever waits on a human (which also
   makes teardown structurally un-blockable). Guardrails are the concurrency
   group, the $10 budget alarm, and the alert channels. ADR-0010 records the
   deliberate omission.
3. **Pipeline structure:** phased make targets shared by laptop and CI
   (`demo-infra-up` / `demo-images` / `demo-app-deploy` / `demo-down`); the
   workflow's jobs mirror the phases 1:1. One orchestration code path.
4. **KMS:** stop creating a per-cluster CMK (`create_kms_key = false`) — ends
   the ~$1/mo pending-deletion accrual per run; recorded honestly in ADR-0010.
5. **Lifecycle events on SNS, filtered email (revised at user review):** one
   foundation-stack topic carries `demo-ready` (info: the ALB URL),
   `run-summary` (info: green/red + cost), and `teardown-failed` (alert) —
   each published with a `severity` message attribute. The email subscription
   (dcltdw@protonmail.com) carries a **filter policy `severity=alert`**: the
   inbox gets only failures by default; loosening to info events is a
   one-line subscription change. Teardown failure remains triple-channel:
   auto-created GitHub issue (GITHUB_TOKEN, AWS-independent) + the SNS email
   + the $10 budget alarm as the slow money backstop. (At this volume SNS is
   $0: publishes and email deliveries sit far inside the free tier, and
   events with no matching subscriber are dropped silently by design.)
6. The three M3 hardening tickets fold in: smoke **hard-fails**, secrets via
   `--set-file` (never command-line args), `demo-cost` degrades gracefully
   when Cost Explorer isn't ingested.

## Goals

1. One button: a maintainer dispatches the pipeline and ~35 minutes later
   has a green public run proving the full lifecycle — with screenshots, a
   Trivy report, and an SBOM as downloadable artifacts. No further clicks.
2. A red run cannot strand billable resources silently: destroy always runs,
   is re-runnable from any state, and its own failure triggers three
   independent alarms.
3. The apply-capable role is scoped to this stack and reachable only through
   the single `aws-deploy` Environment sub — no long-lived keys,
   fork-unreachable triggers, and no job ever waits on a human.
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
`aud = sts.amazonaws.com`, and `sub` StringEquals **exactly one value**:
`repo:dcltdw/annotated-maps-sp:environment:aws-deploy`.

### 2. The Environment and the deliberately-omitted gate (ADR-0010's core)

**One Environment, no protection rules.** All AWS jobs in the pipeline
declare `environment: aws-deploy` — an *unprotected* Environment whose sole
remaining function is to namespace the OIDC subject: the deployer role
trusts exactly `repo:…:environment:aws-deploy`, which only jobs of this
repo's workflows declaring that Environment can present, on any branch
(needed for PR-branch iteration) and for both triggers. It also gives a
deployment-history trail in the repo UI for free.

**Why no reviewer gate (the ADR-0010 decision):** `workflow_dispatch` and
`schedule` cannot be triggered by forks, and dispatching requires write
access — on this repo, the person clicking "Run workflow" is the same person
who would click "Approve," so a required-reviewer rule is a second
confirmation of a deliberate ~\$2 action, bought at the cost of friction on
every run AND a structural risk: GitHub requests Environment approval per
*job*, so any reviewer-gated Environment touching the destroy job could
leave teardown hanging on a human click — the stranded-billing failure this
milestone exists to prevent. The protected-Environment pattern is already
demonstrated where it earns its keep (`infra-plan`, where genuinely
untrusted fork PRs exist). Guardrails that remain: write-access-only
dispatch, the `concurrency` group (no overlapping spend), the \$10 budget
alarm, and the three-channel teardown alerting. If a reviewer gate is ever
reinstated, it must sit at ENTRY only (the provision job), never on any
downstream job.

Cost posture: manual runs ≈ $1–2 each; scheduled = 12 runs/yr ≈ $15–25/yr;
the $10/mo budget alarm already covers both.

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
   + doctype within the window or exit 1). Output: the ALB URL. On success,
   publishes **`demo-ready`** (severity=info, the ALB URL) to the SNS topic.
4. **e2e** — Playwright against `BASE_URL=http://<ALB>` (a small
   `playwright.alb.config.ts` reading `BASE_URL` from env; a smoke-scoped
   spec: app loads, personas render, API answers). **Screenshots uploaded
   `if: always()`** — evidence on green, diagnosis on red.
5. **destroy** — **`if: always()`**, own OIDC auth: `make demo-down`
   (uninstall → wait-ALB-gone → terraform destroy → sweep), delete the Neon
   branch (tolerate already-gone), print `make demo-cost`, and publish
   **`run-summary`** (severity=info: overall run result + the cost line).
   This is the same re-runnable-from-any-state script M3 proved.
6. **alert-teardown-failure** — runs only if destroy failed: creates a
   GitHub issue titled "🔴 TEARDOWN FAILED — billable AWS resources may be
   running" (run URL + sweep output; via GITHUB_TOKEN, AWS-independent) AND
   publishes **`teardown-failed`** (severity=**alert** — the one event the
   email filter passes) to the SNS topic → email to dcltdw@protonmail.com
   (via OIDC if AWS auth works; the issue fires regardless). Backstop: the
   $10 budget alarm.

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
  `dcltdw@protonmail.com` with **`filter_policy = { severity = ["alert"] }`**
  (one-time "Confirm subscription" click at the checkpoint; loosen the
  filter to `["alert","info"]` anytime to also receive demo-ready/summary
  events). Output: topic ARN. All publishes carry a `severity` message
  attribute. The budget alarm stays as-is.
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
  PR branch (runs start immediately): expect 2–4 runs at ~$1–2; **ceiling
  $10**, never-leave-up (the destroy job is the rule; manual sweep after any
  red run), per-run cost line in the ledger.
- **The proof:** after merge, **one green run from `main`** — public in the
  Actions history with screenshots/Trivy/SBOM artifacts — is the roadmap's
  "done means." Then the monthly cron is live. Teardown-alerting is verified
  once by forcing the alert path (publish a test SNS message + a dry-run of
  the issue step), not by deliberately stranding a cluster.

### 9. ADR-0010 — an apply-capable role for the pipeline

House style. Content: the deliberately-omitted reviewer gate (dispatch =
confirmation; why dispatch/schedule triggers change the threat model vs PRs;
the per-job approval mechanic that would have made a gated destroy hangable;
the entry-only rule if a gate is ever reinstated); the deployer-role scoping
stance (broad service powers, hard boundary at IAM-by-prefix + state-bucket
+ one SNS topic); the SNS lifecycle-events-with-filter-policy pattern (inbox
gets alerts, topic carries everything); KMS-off-by-default for the ephemeral
cluster (cost vs a checkbox); per-run Neon branches (the one new secret is
an API key, not a database credential). Alternatives considered:
reviewer-gated dispatch (friction + the hangable-teardown risk for a second
confirmation by the same human), alerts-only SNS, persistent KMS key in
foundation (+$12/yr for a checkbox).

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
2. Agent creates the single unprotected `aws-deploy` GitHub Environment and
   applies the foundation additions (deployer role + SNS topic + filtered
   subscription).
3. You click the SNS **"Confirm subscription"** email once.
4. Live iteration begins: runs are dispatched and proceed immediately (no
   approval clicks).

### 12. PR slicing (revised at user review: small, single-purpose PRs)

Eight focused PRs, decomposed by dependency rather than phase. A/B/C/E/F are
mutually independent (any order, parallelizable); D follows C; G integrates
B–F; H follows the green run.

| PR | Content | Depends on |
|---|---|---|
| **A** | KMS off: `create_kms_key = false` in `demo/eks.tf` | — |
| **B** | Script refactor (three phase targets) + the 3 hardening fixes | — |
| **C** | Foundation: SNS topic + filtered email subscription | — |
| **D** | Foundation: deployer role (trust = `aws-deploy` env sub; `sns:Publish` scoped to C's topic) | C |
| **E** | `neon-branch.sh` (create/delete) + `demo-down` delete-if-named hook | — |
| **F** | Playwright `BASE_URL` config + ALB smoke spec | — |
| **G** | `demo-pipeline.yml` + actionlint in CI + **ADR-0010** (the decisions this PR embodies); the live budget-boxed iteration happens on this branch | B, C, D, E, F |
| **H** | Evidence page + primer §pipeline + README/ROADMAP flip + board → Done | the green run from `main` |

The user checkpoint (§11) attaches to the PRs that need it rather than being
one gate: the SNS confirm-click and foundation apply at C/D's merges; the
`NEON_API_KEY` secret before E is exercised; the `aws-deploy` Environment
before G's first dispatch. One plan document covers all eight — each task =
one PR (implement → verify → open) — rather than eight ceremony-heavy plans.

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
- **Accidental dispatch** — accepted: dispatch requires write access and a
  deliberate click; cost of a mistake is one ~$1–2 fully-self-cleaning run
  (accepted in ADR-0010).

## Testing summary

Static: shellcheck + terraform gates + actionlint + helm/obs-checks (PR-1).
Live: budget-boxed branch dispatches (≤$10) → merge → one green public run
from main with artifacts (the roadmap proof) → monthly cron live. Alert path
verified by forced test message, not a stranded cluster.
