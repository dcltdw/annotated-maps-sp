<!-- doc-status: dated -->

# Lessons learned — bugs the verification loop caught

A running log of the non-obvious bugs found while building the
production-engineering milestones (Kubernetes/Helm → Observability → AWS →
the ephemeral pipeline), and the lesson each one carries. It complements the
[ADRs](adr/), which record *decisions*; this file records *gotchas* — the
things that were wrong and how they surfaced.

Each entry names **how it was found** — because that's the interesting part.
Of the twenty-four below:

| Found via | Count |
|---|---|
| Only when the real thing ran (a live deploy or end-to-end verification) | 11 |
| An adversarial code review, before it could bite | 7 |
| CI, after passing locally | 2 |
| A security gate doing its job | 1 |
| **Reading a green run's own artifact** | 1 |
| Anticipated in design | 2 |
| **Unit tests** | **0** |

They all lived at **integration seams** (a Helm hook boundary, an HTTP `Host`
header, a log-export path, a cloud IAM trust policy, an ephemeral-runtime
behavior) where unit tests are blind. Several are the same underlying mistake
recurring at a new layer: the `ALLOWED_HOSTS` host-header footgun appears three
times at three scales, and "a new file silently falls outside a hand-maintained
gate list" appears twice in one milestone.

The discipline that paid off: *verify the running system, and have a fresh
reviewer try to break every claim before trusting it.* Milestone 4 added two
uncomfortable corollaries — **an adversarial review can confirm a control is
correct and still miss what it costs** (#15), and **a green run is not evidence;
the artifact is** (#19).

---

## Milestone 1 — Kubernetes & Helm

### 1. A pre-install Helm hook can't depend on a resource the release creates
- **Found via:** live deployment — the first `make deploy` on kind failed.
- **Symptom:** a fresh `helm install` hung — the database-migration hook timed out waiting to connect.
- **Root cause:** the migration ran as a `pre-install` hook, but the in-cluster Postgres it needed is a *main-phase* resource that doesn't exist yet during pre-install. The DB-wait never connected.
- **Fix:** values-gate the hook phase — `post-install` when the database is born in the release (in-cluster dev), `pre-install` when it pre-exists (external DB).
- **Takeaway:** a `pre-install` hook may only depend on things that already exist. If the dependency is created by the same release, the hook must run `post-install`.

### 2. `.dockerignore` is relative to the build *context*, not the Dockerfile
- **Found via:** live deployment — the API image crash-looped in-cluster on kind.
- **Symptom:** a local `.env` carrying a macOS-specific GDAL library path had been baked into the image.
- **Root cause:** the image builds with the repo root as its context (`docker build -f backend/Dockerfile .`), so `backend/.dockerignore` was never consulted — and the root had none.
- **Fix:** a root `.dockerignore` excluding `backend/.env`, caches, and test dirs.
- **Takeaway:** `.dockerignore` belongs with the build context directory, which is often *not* where the Dockerfile sits. Check the context path.

### 3. Kubernetes probes trip Django's `ALLOWED_HOSTS`
- **Found via:** design — flagged as a known Django-on-Kubernetes footgun while designing the M1 chart, and handled up front (it later bit for real, at cloud scale — see #5).
- **Symptom:** without mitigation, liveness/readiness probes return 400 and pods never become Ready.
- **Root cause:** the kubelet sends `Host: <podIP>` on HTTP probes by default, and `ALLOWED_HOSTS` doesn't include it → `DisallowedHost`.
- **Fix:** set an explicit, allow-listed `Host` header on the probes.
- **Takeaway:** anything that reaches Django by IP (probes, scrapers) hits host validation. Anticipating it once didn't stop it recurring where it *wasn't* anticipated — see #5.

---

## Milestone 2 — Observability

### 4. A logging change made to satisfy a test silently broke log export
- **Found via:** code review — the Task-1 review traced an implementer-flagged logger-factory change to a broken export path.
- **Symptom:** every test passed, but application logs would never have reached Loki.
- **Root cause:** structlog's `logger_factory` had been switched to `PrintLoggerFactory` to make a test's stdout capture work. That bypasses the stdlib root logger — which is precisely where the OpenTelemetry `LoggingHandler` attaches. Logs went to stdout but were never exported.
- **Fix:** revert to `stdlib.LoggerFactory`, fix the *test's* capture instead, and add a regression guard asserting structlog records reach the stdlib root logger.
- **Takeaway:** never bend production wiring to satisfy a test harness. Know the export path end to end — and guard it with a test that would fail if the path breaks again.

### 5. `ALLOWED_HOSTS` vs. the Prometheus pod-IP scrape (footgun #3, cloud-scale)
- **Found via:** live verification — standing up the in-cluster monitoring stack showed the Prometheus scrape target DOWN.
- **Symptom:** the in-cluster dashboards were silently empty.
- **Root cause:** Prometheus scrapes each pod at its IP, so the pod IP arrives as the `Host` header → `DisallowedHost` 400. The `/metrics` CI smoke had used a `localhost` Host, so it never exercised the real scrape path and never caught this.
- **Fix:** inject each pod's own IP via the downward API and append it to `ALLOWED_HOSTS`; strengthen the CI smoke to curl with the pod-IP `Host`.
- **Takeaway:** test the path production actually uses. A smoke test that doesn't imitate the real caller proves nothing.

### 6. A whitespace mismatch in a log↔trace correlation regex
- **Found via:** code review — the Task-2 reviewer caught the regex not matching the app's actual log format.
- **Symptom:** clicking a log line's trace link in Grafana would do nothing.
- **Root cause:** the derived-field regex matched `"trace_id":"…"`, but the app emits `"trace_id": "…"` — Python's `json.dumps` default separators include a space after the colon.
- **Fix:** tolerate the whitespace (`\s*`).
- **Takeaway:** match the bytes that are actually serialized, not the shape you picture in your head.

### 7. Public Grafana dashboards don't resolve a datasource *variable*
- **Found via:** live verification — a headless load of the public dashboard URL *as an anonymous visitor* rendered "No data," though it worked when logged in.
- **Symptom:** every panel empty for anyone not signed in.
- **Root cause:** Grafana public dashboards don't resolve a `datasource` template variable — every panel query ran with no datasource.
- **Fix:** hardcode the datasource UID and drop the variable.
- **Takeaway:** the anonymous/public rendering path has different capabilities than the authenticated one. Verify *as the anonymous viewer* — logging in hides exactly this class of bug.

### 8. Cold-start counter resets produce `rate()` artifacts
- **Found via:** live verification — the headless screenshot of the public dashboard showed the spike.
- **Symptom:** the public error-ratio panel spiked to 10000%.
- **Root cause:** the free-tier host cold-starts, resetting the cumulative OTLP counters; `rate()`'s extrapolation across the reset produced a nonsensical value.
- **Fix:** `clamp_max(…, 1)` on the query and bound the panel axis to 0–100%.
- **Takeaway:** ephemeral/restarting services generate counter-reset artifacts. Bound ratio panels and expect resets rather than assuming monotonic counters.

---

## Milestone 3 — AWS infrastructure as code

### 9. A fork-assumable OIDC trust policy (public-repo footgun)
- **Found via:** code review — the Task-3 reviewer flagged it before it ever ran.
- **Symptom:** the CI role's trust would have been assumable by any stranger, not just this repo.
- **Root cause:** GitHub sets a `pull_request` run's OIDC `sub` to `repo:<BASE-OWNER>/<BASE-REPO>:pull_request` — the **base** repo, even for a PR opened from a fork. On a public repo, anyone could fork, add a workflow that requests a token, open a PR, and assume a role that trusted `…:pull_request`.
- **Fix:** pin the trust to `…:ref:refs/heads/main` (push-to-main); to keep plan-on-PR, gate it behind a protected GitHub **Environment** whose sub is `…:environment:NAME` (fork PRs then pause for human approval) — never bare `pull_request`.
- **Takeaway:** the `pull_request` OIDC sub does not distinguish forks. On a public repo, trusting it is a credential-exposure bug.

### 10. An optional value templated into a required field
- **Found via:** code review — flagged in the Task-4 review, and `kubeconform` on the demo values would have rejected the null outright.
- **Symptom:** the demo values (with an empty Ingress host) failed strict `kubeconform` and would have failed the probes at deploy time.
- **Root cause:** the probe `Host` header was `{{ .Values.ingress.host }}`; with the host empty, it rendered `null`.
- **Fix:** `{{ .Values.ingress.host | default "localhost" }}`, and allow-list `localhost` in the demo values.
- **Takeaway:** any optional value that feeds a required field needs a default *at the templating boundary* — and every values file the chart ships should be rendered in CI (this slipped because only the default and prod value sets were kubeconform'd, not the demo set; now all three are).

### 11. A teardown poll that couldn't tell "empty" from "errored"
- **Found via:** code review — the Task-5 reviewer flagged the safety-critical case in the teardown script.
- **Symptom:** a transient AWS API error during teardown could race `terraform destroy` into the orphaned-load-balancer hang (a half-destroyed, still-billing VPC).
- **Root cause:** `COUNT=$(aws elbv2 … || echo 0)` treated an API *failure* identically to "no load balancers left," so a blip would report "gone" and let destroy proceed while the ALB still existed.
- **Fix:** capture the exit code; only treat a *successful, empty* result as "gone," and keep waiting on any error.
- **Takeaway:** in a `set +e` teardown script, distinguish "the query succeeded and returned nothing" from "the query failed." `|| echo 0` silently conflates them — the most dangerous place for it, since a false "all clear" here costs money.

### 12. The migration Secret must be a pre-install hook on the external-DB path
- **Found via:** live deployment — the *first real EKS deploy* on live AWS failed here.
- **Symptom:** the migrate hook pod reported `secret "annotated-maps-secrets" not found`, then hit its 300s deadline.
- **Root cause:** with an external database, the migration runs as a `pre-install` hook, but the shared Secret it reads was a normal (main-phase) resource — created *after* pre-install hooks. The hook (and, moments later, the app pods) had no Secret. Milestone 1 had only ever exercised the in-cluster-DB path (a `post-install` hook, where the main-phase Secret already exists), so the external-DB ordering was never actually run until real AWS hit it.
- **Fix:** when the DB is external, annotate the Secret itself as a `pre-install` hook at a lower weight (`-5`) than the migrate hook (`0`), so it is created first.
- **Takeaway:** *test the code path you actually ship.* A values-gated branch that has never been run in its gated configuration is untested, no matter how green the suite is — and this is the strongest argument for spending the money on one real end-to-end deploy. (Also, restated: pre-install hooks can't depend on main-phase resources — the same lesson as #1, one layer down.)

### 13. Preflight the daemons; make failures cheap to resume
- **Found via:** live deployment — `demo-up` cycle 1 failed at the image-build step.
- **Symptom:** `docker.sock: no such file` (Docker Desktop was stopped).
- **Root cause:** an environmental prerequisite, not a code bug.
- **Fix:** start Docker and re-run. Because the cluster had already been applied, the re-run's `terraform apply` was a fast no-op — the failure cost minutes, not a full re-provision.
- **Takeaway:** two things — preflight-check prerequisites (a clear "Docker isn't running" beats a cryptic socket error), and design multi-step deploy scripts so a mid-way failure resumes cheaply (idempotent apply, reuse of already-provisioned infrastructure).

---

## Milestone 4 — The one-button ephemeral pipeline

### 14. The IAM boundary would have broken the destroy it existed to protect
- **Found via:** code review — an adversarial reviewer traced the resolved EKS module source rather than reading the policy alone.
- **Symptom:** none yet — it would have failed the first live `terraform apply`, and then the `destroy`.
- **Root cause:** the deployer role scoped `iam:*` to `role/`, `policy/` and `instance-profile/` ARNs matching `annotated-maps-*`. But `enable_irsa = true` makes the module create an OIDC provider whose ARN is `oidc-provider/oidc.eks.<region>.amazonaws.com/id/<hash>` — matching none of them. Create *and delete* would have hit `AccessDenied`.
- **Fix:** scope by issuer host (`oidc-provider/oidc.eks.*`), which deliberately does **not** match the foundation's GitHub provider, so the deployer cannot delete CI's trust anchor.
- **Takeaway:** a resource-prefix boundary only covers ARNs shaped like the ones you thought of. Enumerate what the *module* creates, not what your own code names. The expensive half here was the destroy: a permission gap that strands billable infrastructure is worse than one that blocks a build.

### 15. A security control that broke the apply — and the review that blessed it
- **Found via:** **the first live run.** Static gates, and the adversarial review that *recommended the control*, both passed it.
- **Symptom:** `terraform apply` died at data-source evaluation, before creating a single resource: `AccessDenied … with an explicit deny in an identity-based policy`.
- **Root cause:** to close a one-call self-escalation path, the deployer role carried a blanket `iam:*` **Deny** on its own ARN. But the EKS module's `data "aws_iam_session_context" "current"` resolves the *caller's own* STS source role — needing `iam:GetRole` on that very role.
- **Fix:** deny only the **mutating** actions (`AttachRolePolicy`, `PutRolePolicy`, `UpdateAssumeRolePolicy`, `Delete`/`Create`/`UpdateRole`, permissions-boundary writes). Reads don't escalate; mutations do. An `Allow` cannot carve an exception out of a `Deny`, so the action list itself has to be precise.
- **Takeaway:** the reviewer explicitly checked "nothing legitimate breaks" and still missed it, because the dependency was *indirect, module-internal, and caller-relative* — not a hardcoded reference anyone could grep for. **An adversarial review can verify that a control is correct and still miss what it costs.** Deny-by-default controls need a live exercise, not just an argument.

### 16. A half-granted permission: create without read
- **Found via:** **live run** — after building a real 67-resource cluster.
- **Symptom:** `CreateNodegroup` failed: *"Failed to validate if SLR: AWSServiceRoleForAmazonEKSNodegroup already exists due to missing permissions for `iam:GetRole`"*.
- **Root cause:** the role granted `iam:CreateServiceLinkedRole` on `role/aws-service-role/*` but not `iam:GetRole`. EKS *reads* the service-linked role to decide whether to create it.
- **Fix:** add `iam:GetRole` on the same path.
- **Takeaway:** "create" permissions usually imply a read the API performs first. A grant that lets you create a thing but not look at it is a half-grant, and the error surfaces at the *caller* (EKS), not at IAM, so it reads like a service bug.

### 17. A teardown alarm blind to cancellation
- **Found via:** code review — the reviewer reasoned about the states a job can end in, not just the happy and sad paths.
- **Symptom:** none yet — it would have gone silent in exactly the case it existed for.
- **Root cause:** the alarm fired on `needs.destroy.result == 'failure'`. A human cancelling a run mid-`terraform destroy` yields `cancelled`, not `failure` — so infrastructure could be left half-up with **no GitHub issue and no email**.
- **Fix:** `needs.destroy.result != 'success'`.
- **Takeaway:** when an alarm's job is "tell me if the safety net didn't work," enumerate the *non-success* states rather than the failure state. `!= 'success'` is the safe default; `== 'failure'` silently excludes `cancelled` and `timed_out`.

### 18. The scan gate caught a real CVE — and the temptation was to suppress it
- **Found via:** **the Trivy gate itself**, on its first live run.
- **Symptom:** the `images` job failed and refused to push: `CVE-2026-31789`, openssl heap overflow via large X.509 certs — `libcrypto3`/`libssl3` at `3.3.3-r0`, fixed in `3.3.7-r0`.
- **Root cause:** `nginx:1.27-alpine` is rebuilt on upstream's own cadence, so its Alpine packages lag the security repo. The base image was simply behind.
- **Fix:** `RUN apk --no-cache upgrade` in the Dockerfile — which also fixes the *next* such CVE, unlike pinning a version that goes stale.
- **Takeaway:** the CVE was 32-bit-only and these images run on amd64, so a `.trivyignore` was defensible and tempting. It was still the wrong call: the gate's stated policy is "CRITICAL **and** fixable", this was both, and reaching for an ignore the first time a control ever fires is how controls become decoration. Also note what made the finding *usable*: the SBOM steps carried `if: always()` (added in review), so the software inventory was captured even though the gate had tripped.

### 19. A test that could not fail — on a green run
- **Found via:** **reading a green run's own artifact.** Static gates, an adversarial code review, and a fully green live pipeline all passed it.
- **Symptom:** the pipeline went green and uploaded its evidence screenshot. The screenshot was a **blank grey rectangle**. The map had rendered nothing.
- **Root cause:** the smoke asserted `expect(page.locator("canvas")).toBeVisible()`. maplibre creates its canvas the instant it initialises, so the assertion is satisfied by a map that has drawn nothing at all. The test could not fail on the one thing it existed to prove.
- **Fix:** wait for a rendered `.maplibregl-marker` — the idiom the existing suite already used. A marker appears only once the basemap style has loaded *and* the API's seeded notes arrived, so it genuinely proves ALB → web → API → database → render.
- **Takeaway:** **a green run is not evidence; the artifact is.** Ask of every assertion: *what state of the world would make this fail?* If the answer is "almost none," it is decoration. This one survived every gate we had, and the only thing that caught it was a human looking at the picture the pipeline produced.

### 20. Gate lists rot — the same bug twice in one milestone
- **Found via:** CI (once), and reading a diff (once).
- **Symptom:** (a) vitest tried to run a Playwright spec: *"Playwright Test did not expect test() to be called here"*; (b) four of seven shell scripts had merged with no `shellcheck` coverage at all.
- **Root cause:** both were hand-maintained lists that a new file silently fell outside of. vitest's `exclude` named every Playwright directory except the new one; CI's `shellcheck` step named three scripts by hand while the repo had grown to seven.
- **Fix:** add the directory to the exclude; replace the script list with a glob (`shellcheck scripts/*.sh`), which cannot drift.
- **Takeaway:** any gate configured as an enumerated list is a gate that will quietly stop covering things. Prefer a glob or a deny-by-default pattern. Where a list is unavoidable, the thing that adds a file must also update the list — and the plan that told an implementer to add the file should say so, which is precisely what ours forgot.

### 21. "Green locally" did not mean "green in CI"
- **Found via:** CI — after a local run of the same command passed.
- **Symptom:** `shellcheck scripts/*.sh` passed on the laptop and failed in CI on `SC2015`.
- **Root cause:** shellcheck was the only linter in the repo that wasn't pinned — it rode the runner image. Local `0.11.0` had dropped `SC2015` from its defaults; the runner's older build still had it on.
- **Fix:** rewrite the flagged line as a plain `if` (correct under every version, rather than suppressed), and pin CI to `shellcheck v0.11.0` like every other linter here (terraform, tflint, kubeconform, promtool, actionlint).
- **Takeaway:** an unpinned linter is a gate whose rules change without a commit. If local and CI can disagree about what passes, local verification is advisory — and one unpinned tool in an otherwise-pinned toolchain is the one that will bite.


## Milestone 4 follow-ups

### 22. The obvious live test exercised the wrong principal
- **Found via:** planning the live verification — the blind spot was reasoned out before the run, then confirmed by it.

The fix for Path B (ADR-0012) is a set of `Deny` statements on the
`annotated-maps-deployer` role. The natural way to verify it is `make demo-up`
against the real account — but `demo-up` runs `terraform apply` as the
**operator** (an `AdministratorAccess` SSO identity), not as the deployer, and
the deployer's trust policy admits **only** GitHub OIDC, so an operator cannot
`AssumeRole` into it. A local `demo-up` therefore proves the boundary *ceiling*
doesn't break the cluster and exercises **none** of the Deny statements — the
entire security change is invisible to it. Proving the Denys bite needed
`aws iam simulate-principal-policy --policy-source-arn <deployer>` for the
allow/deny matrix (create-without-boundary → `explicitDeny`,
create-with-boundary → `allowed`, boundary-policy rewrite → `explicitDeny`),
which evaluates the deployer's identity policy without assuming the role.
**Takeaway:** the obvious end-to-end test can run as the *wrong principal* and
silently skip the whole control under test. When you can't assume the identity
you're securing, the IAM policy simulator is how you exercise it — two
complementary proofs split by principal: `demo-up` (operator) for "the cap
doesn't break the cluster," the simulator (deployer) for "the Denys bite."

### 23. `demo-up` can't run headless — a secret read wants a TTY
- **Found via:** the live run — a non-interactive `demo-up` died at the app-deploy step after the cluster was already up.

`scripts/demo-app-deploy.sh`'s "app secrets" step reads the Neon `DATABASE_URL`
from `$DB_URL_FILE` when set, and otherwise falls back to an interactive
`read -r -s -p` prompt. Run headless with `DB_URL_FILE` unset, that `read` hits
EOF and fails under `set -e` — and it fails **after** `terraform apply` has
already stood up the whole cluster, so the meter is running when the run aborts.
The infra came up clean; only the app deploy was blocked, by the environment,
not the boundary (the run logged zero `AccessDenied`). **Takeaway:** a script
that is "CI-ready" can still carry an interactive fallback that only bites when
it's run headless *outside* CI — and this one fails past the expensive step. For
an unattended `demo-up`, provide the Neon URL non-interactively via
`DB_URL_FILE`; the prompt is a convenience for a human at a terminal, not a
headless path.

### 24. A "graceful" error path that handled only one of two failure modes
- **Found via:** live use — running `make demo-cost` to pull the real cost figure.

`demo-cost.sh` filtered near-zero services with a JMESPath comparison,
`Amount > 0.001`. PR #52 had already made the tool graceful for the **no-data**
case — a new account's `DataUnavailableException` falls back to an estimate and
exits 0. But Cost Explorer returns `Amount` as a **string**, and a newer awscli
refuses `string > number` (*"'>' not supported between instances of 'str' and
'float'"*) where older builds silently coerced — so the tool broke for the
**has-data** case, the one it exists to serve, while the no-data path kept
working. The graceful handler made the failure *look* covered. The fix (#115)
moves the threshold out of JMESPath into awk, whose numeric context coerces the
string. **Takeaway:** a graceful path that catches one failure mode is easy to
mistake for robustness — it handles the case you thought of and silently exposes
the one you didn't. When you add a fallback for error X, enumerate the *other*
ways the same step can fail; "handles errors" is not "handles this error."

## The meta-lesson

Green unit tests are necessary and not sufficient. The bugs that would have
actually broken production all lived where components *meet* — and were found by
either standing the real thing up (locally on `kind`, then on live AWS) and
watching it serve traffic, or by a skeptical reviewer refusing to believe "it
works" until the evidence was in hand. The two methods catch different classes:
review caught the ones visible in the diff (a broken export path, a
fork-assumable trust policy, a conflated exit code); live verification caught
the ones that only exist at runtime (hook ordering against a real database, a
host header from a real scraper, an anonymous public render, a counter reset).
Every milestone here shipped only after a live end-to-end verification, and
every milestone's live verification caught at least one real bug the tests had
missed.

Milestone 4 sharpened that into two rules worth stating plainly, because both
were learned by being wrong:

**A review can bless a control and still miss its cost.** The `iam:*` self-Deny
(#15) was *recommended* by an adversarial reviewer who explicitly checked that
nothing legitimate would break. It broke the very first apply, because the
dependency was indirect, module-internal and caller-relative — invisible to
anyone reading the diff. Reasoning about a deny-by-default control is not the
same as exercising it.

**A green run is not evidence; the artifact is.** The pipeline went green while
uploading a screenshot of a blank map (#19), because the assertion behind it
could not fail. It had passed static gates, a code review, and a full live
run. What caught it was a person opening the PNG. Every automated gate in this
repo is a claim about reality that is itself worth checking — which is the whole
argument for the pipeline existing, applied to the pipeline itself.
