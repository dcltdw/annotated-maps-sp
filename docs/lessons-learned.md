# Lessons learned — bugs the verification loop caught

A running log of the non-obvious bugs found while building the
production-engineering milestones (Kubernetes/Helm → Observability → AWS), and
the lesson each one carries. It complements the [ADRs](adr/), which record
*decisions*; this file records *gotchas* — the things that were wrong and how
they surfaced.

Each entry names **how it was found** — because that's the interesting part.
Of the thirteen below: **seven surfaced only when the real thing ran** (a live
deploy or an end-to-end verification), **five were caught by an adversarial
code review** before they could bite, and **one was anticipated in design**.
**Zero were caught by unit tests** — they all lived at **integration seams** (a
Helm hook boundary, an HTTP `Host` header, a log-export path, a cloud IAM trust
policy, an ephemeral-runtime behavior) where unit tests are blind. Several are
the same underlying mistake recurring at a new layer (the `ALLOWED_HOSTS`
host-header footgun appears three times, at three scales). The discipline that
paid off: *verify the running system, and have a fresh reviewer try to break
every claim before trusting it.*

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
