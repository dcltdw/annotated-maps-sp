<!-- doc-status: dated -->

# Codebase walkthrough

- Date: 2026-08-26
- Audience: someone who needs to discuss this repo out loud — an interview, a
  design review, a hand-off — and wants the map before the territory.
- Reading time: ~15 minutes.

A guided tour of the five areas that carry the most weight, in the order they
are most often asked about. Each section says **where it lives**, **how it
works**, **what to cite**, and — the part that matters most when speaking from
memory — **what you might get wrong**.

Acronyms are expanded at first use; there is also a
[glossary](#glossary) at the end.

Deeper narrative walkthroughs live in [docs/explainers/](explainers/); the
evidence-first tour for evaluators is [for-reviewers.md](for-reviewers.md).

---

## 1. The rules engine — per-audience content filtering

The single most load-bearing idea in the backend: **the same note shows a
different face to each viewer, decided per piece of content, by a small pure
engine.**

### Where it lives

```
backend/core/visibility/          the pure engine (no Django, no database)
  viewer.py     Viewer — who is looking
  rules.py      VisibilityRule + Public / Private / Audience / AttributeGate
  engine.py     can_view() + the Visibility enum
  resolve.py    user id (+ tenant) -> Viewer   [touches the DB]
backend/maps/visibility.py        the persistence bridge (stored row -> rule)
backend/maps/api.py               wires it into a request
backend/core/auth.py              resolve_identity(): who the caller actually is
backend/maps/sandbox.py           write-side authorization (a separate axis)
```

### How it works

The unit of visibility is a **section**, not a note. A
[Note](../backend/maps/models.py) owns an ordered list of
[Sections](../backend/maps/models.py), and each section carries its own rule as
two columns: `rule_type` (an enum) plus `rule_params` (JSON).

The engine is four dataclasses and one function.
[`can_view`](../backend/core/visibility/engine.py) is the whole decision:

```python
if viewer.user_id is not None and viewer.user_id == owner_id:
    return Visibility.VISIBLE      # owner-sees-all, before any rule
if rule.grants(viewer):
    return Visibility.VISIBLE
return Visibility.TEASER if teaser else Visibility.HIDDEN
```

A rule answers exactly one question — `grants(viewer) -> bool`. Four exist:
`Public`, `Private`, `Audience(user_ids, group_ids)`, and
[`AttributeGate(attribute, threshold)`](../backend/core/visibility/rules.py),
which is the reputation gate.

A request resolves in three moves, all visible in `list_notes` in
[maps/api.py](../backend/maps/api.py):

1. **`resolve_identity(request, preview_as)`** in
   [core/auth.py](../backend/core/auth.py) — a valid bearer token always wins;
   `preview_as` is honored *only* for an anonymous visitor *and only* under
   `SANDBOX_MODE`; otherwise guest.
2. **`resolve_viewer(user_id, tenant)`** in
   [core/visibility/resolve.py](../backend/core/visibility/resolve.py) — loads
   the user's groups *scoped to this tenant* and their reputation into
   `Viewer.attributes`.
3. **`_visible_sections(note, viewer)`** — runs the engine per section.
   `HIDDEN` means the section is skipped entirely; `TEASER` means `content` is
   `null` but `teaser_text` is included; `VISIBLE` means content is included.

Then one note-level rule: **a note with zero visible sections is dropped from
the response** — no title, no coordinate, no pin on the map.

### What to cite

- **Fail closed by construction.** `rule_for()` in
  [maps/visibility.py](../backend/maps/visibility.py) returns `Private()` for an
  unknown `rule_type` *and* for malformed `rule_params`. The worst a corrupt
  rule can do is hide something that should have shown. There is no code path
  where a mistake reveals content.
- **A guest is `Viewer()`** — no id, no groups, no attributes. It fails every
  identity- and attribute-based rule by construction, with zero special-casing.
  That emptiness is load-bearing.
- **Three states, not two.** `TEASER` is what lets the interface say "the author
  wrote a members-only note here" without leaking it. It is opt-in per section
  (`Section.teaser`) with custom hook text.
- **Invariants are proved, not sampled.** The engine is unit-tested with
  Hypothesis property tests in
  [test_properties.py](../backend/core/tests/visibility/test_properties.py):
  arbitrary viewers are generated and invariants asserted — *public is always
  visible*, *private is never visible to a non-owner*, *the owner is visible
  under any rule*.

### What you might get wrong

| Easy to misstate | What is actually true |
|---|---|
| "The database query filters by audience" | **No — filtering happens in Python, per section, after the query.** `list_notes` fetches all top-level notes for the map with `select_related` / `prefetch_related`, then loops. There is no SQL-level access-control list. |
| "Notes have a visibility setting" | Notes do not. **Sections do.** Note-level invisibility is *emergent*: zero visible sections means the note is dropped. |
| "Multi-tenant with row-level isolation" | `tenant_id` is threaded onto every domain row, but **Postgres RLS (Row-Level Security) is deliberately not enabled** — see [ADR-0005](adr/0005-rls-tenant-isolation-deferred.md). `GET /maps` does `Map.objects.all()` with no tenant filter. Say "the column and access paths are threaded; RLS is the recorded next step." |
| "Each rule handles the owner case" | Owner-sees-all is a property of **the engine**, checked once, first. Individual rules never think about it. |
| "`preview_as` lets you view as anyone" | It **was** an impersonation hole; it is closed. A bearer token always wins, and `preview_as` is ignored entirely outside `SANDBOX_MODE`. Tell it as the fix, not the feature. |
| "Visibility controls editing too" | Separate axis. Writes go through `authorize_write` / `is_editable` in [maps/sandbox.py](../backend/maps/sandbox.py): authenticated callers own content by author id; anonymous sandbox callers own it by **session key**; seed content is read-only either way. |
| "Reputation is special-cased" | `AttributeGate` is generic — any named attribute plus a numeric threshold. Only `reputation` is currently populated into `Viewer.attributes`. |

---

## 2. REST API design and data modeling

### Where it lives

[annotated_maps/api.py](../backend/annotated_maps/api.py) (router assembly) ·
[maps/api.py](../backend/maps/api.py) (notes) ·
[maps/schemas.py](../backend/maps/schemas.py) (contracts) ·
[core/auth_api.py](../backend/core/auth_api.py) ·
[maps/mod_api.py](../backend/maps/mod_api.py) ·
[core/models.py](../backend/core/models.py) ·
[maps/models.py](../backend/maps/models.py)

### How it works

**Django Ninja**, not DRF (Django REST Framework) — see
[ADR-0002](adr/0002-tech-stack.md). Function-based routes with Pydantic schemas,
so request and response contracts are types and an OpenAPI document comes for
free. Four routers mount under `/api/v1/`: core (health), maps, moderation, and
auth.

The model spine is `BaseModel` in [core/models.py](../backend/core/models.py):
a UUID primary key, `created_at` / `updated_at`, a `version` counter, and
`deleted_at` for soft delete. `TenantScopedModel` adds the tenant foreign key.

The endpoint surface, roughly:

```
GET    /api/v1/health
GET    /api/v1/maps
GET    /api/v1/maps/{id}/viewers      /groups
GET    /api/v1/maps/{id}/notes?preview_as=<uuid>
POST   /api/v1/maps/{id}/notes
GET    /api/v1/notes/{id}/edit
PUT    /api/v1/notes/{id}             DELETE /api/v1/notes/{id}
POST   /api/v1/notes/{id}/appends     PUT    /api/v1/appends/{id}
POST   /api/v1/auth/signup /login /logout    GET /api/v1/auth/me
GET    /api/v1/mod/recent             POST   /api/v1/mod/delete
```

### What to cite

- **Optimistic concurrency, resolved by the database.** `update_note` does not
  read-then-write. It issues
  `Note.objects.filter(id=..., version=payload.version).update(version=F("version") + 1, ...)`.
  Exactly one of two racing `PUT`s can match; the loser updates zero rows and
  gets a **409**.
- **The same invariant enforced at two layers.** A top-level note is anchored to
  exactly one of `point` / `area` / `path` — checked by a Pydantic
  `_exactly_one_anchor` validator in
  [schemas.py](../backend/maps/schemas.py) *and* by a Postgres `CheckConstraint`
  in [models.py](../backend/maps/models.py), with appends explicitly exempt.
  Validation for the error message; the constraint so bad data cannot exist.
- **A read/write contract split.** `NoteOut` returns the *filtered* view plus a
  server-computed `editable` boolean; `NoteEditOut` returns the *unfiltered*
  authoring view (raw `rule_params`, the version to submit back). The client
  never guesses at permissions.
- **Two managers, deliberately asymmetric.** `objects` filters soft-deleted
  rows; `all_objects` does not. `base_manager_name = "all_objects"` so foreign
  key and prefetch integrity survive, while `default_manager_name = "objects"`
  keeps deleted rows out of the API — with a comment warning subclasses not to
  override it.

### What you might get wrong

- **It is Django Ninja, not DRF.** No serializers, no ViewSets — Pydantic
  schemas and plain functions.
- **There is no `django.contrib.auth`.** It is not in `INSTALLED_APPS`. `User`
  is a custom model, and auth is a hand-rolled **bearer-token session**:
  `create_session` mints a 256-bit `secrets.token_urlsafe(32)` and stores
  **only the SHA-256 hash**, never the raw token. Not JWT. The code comments
  why a fast hash is correct here — the token is high-entropy, so a slow
  key-derivation function would buy nothing.
- **Versioning is in the URL path** (`/api/v1/`), alongside
  `NinjaAPI(version="1.0.0")`.
- **`PUT /notes/{id}` replaces sections wholesale with a *hard* delete.**
  `QuerySet.delete()` bypasses soft delete. It is intentional and commented as
  known debt for a future revision-history slice. Worth volunteering — it reads
  as sloppiness if someone finds it first.
- **Appends are single-level by design.** You can only append to a top-level
  note; `create_append` returns 400 otherwise. A deliberate call, not an
  oversight.

---

## 3. Third-party integration and external boundaries

| Boundary | Where | How it is handled |
|---|---|---|
| **Map tiles** | [MapView.tsx](../frontend/src/components/MapView.tsx) | MapLibre GL against `https://tiles.openfreemap.org/styles/positron` — **no API key, no Mapbox account, no vendor lock**. |
| **Neon Postgres** | [settings.py](../backend/annotated_maps/settings.py), [neon-branch.sh](../scripts/neon-branch.sh) | Serverless Postgres with PostGIS, **a branch per environment**. The pipeline creates `ci-run-<id>` per run and deletes it on teardown. |
| **Grafana Cloud** | [telemetry.py](../backend/annotated_maps/telemetry.py), [render.yaml](../render.yaml) | OpenTelemetry Protocol (OTLP) export. `OTEL_ENABLED` defaults to **false** — telemetry is opt-in config, not a hard dependency. |
| **AWS** | [deploy/terraform/](../deploy/terraform/) | ECR (Elastic Container Registry), an Application Load Balancer (ALB), SNS for alerts, S3 for Terraform state. GitHub authenticates via **OIDC (OpenID Connect) federation — no long-lived keys anywhere**. |
| **Render** | [render.yaml](../render.yaml) | The always-on demo host: the API as a Docker service, the compiled SPA (Single-Page Application) as a static site, and a nightly reaper cron job. |
| **Trivy** | [demo-pipeline.yml](../.github/workflows/demo-pipeline.yml) | Scans container images for known CVEs (Common Vulnerabilities and Exposures) as a **push gate**, plus CycloneDX software bills of materials. |

### What to cite

- **Exactly one pod in the cluster has AWS permissions**, and
  [iam-irsa.tf](../deploy/terraform/demo/iam-irsa.tf) says why: the load-balancer
  controller, because it is the only one that needs them — the application talks
  to Neon over TLS and calls no AWS API at all. Its trust policy binds it to
  *one* service account in *one* cluster.
- **Secret hygiene in the Neon script.** The API key travels only in the
  `Authorization` header, and the connection string is written to a **file**
  for `helm --set-file`, never echoed to a log. It also rewrites
  `postgresql://` to `postgis://`, because GeoDjango needs the spatial backend.
- **The database engine is forced, not trusted.**
  [settings.py](../backend/annotated_maps/settings.py) overrides `ENGINE` to the
  PostGIS backend unconditionally, because Neon and Render hand out
  `postgresql://` strings that `env.db()` would otherwise map to the
  non-spatial backend.
- **The load-balancer controller's IAM policy is vendored, not fetched** — a
  pinned JSON file under
  [deploy/terraform/demo/policies/](../deploy/terraform/demo/policies/) with the
  version in its header, so it is reviewable and diffable rather than changing
  under you at apply time.

### What you might get wrong

- **No geocoding, routing, or search API.** No Google Maps, no Mapbox.
  `terra-draw` is a client-side drawing library, not a service.
- **`X-Forwarded-For` uses the *rightmost* hop, not the leftmost** — and
  [sandbox.py](../backend/maps/sandbox.py) explains why: a client can forge
  leftmost hops, so the trustworthy value is the one the platform itself
  appends. State the assumption it rests on: exactly one trusted proxy in front
  of the app.
- **The database is external in every environment except local kind.** The
  in-chart Postgres StatefulSet is `postgres.enabled` and development-only.

---

## 4. Deployment, infrastructure, and Kubernetes

### The Helm chart

[deploy/helm/annotated-maps/](../deploy/helm/annotated-maps/) covers the whole
application: the API as a Deployment (2 replicas, liveness and readiness probes,
resource requests and limits), the web tier as a Deployment, Services, an
Ingress, an **HPA (HorizontalPodAutoscaler)** scaling 2 to 4 pods at 70% CPU, a
**PDB (PodDisruptionBudget)** with `minAvailable: 1`, **database migrations as a
pre-upgrade hook Job** ([ADR-0007](adr/0007-migrations-via-helm-hooks.md)), the
reaper as a native CronJob, a Secret, and the monitoring trio (ServiceMonitor,
PrometheusRule, dashboard ConfigMap). Three value sets:
[values.yaml](../deploy/helm/annotated-maps/values.yaml) for kind,
[values-prod.yaml](../deploy/helm/annotated-maps/values-prod.yaml), and
[values-demo.yaml](../deploy/helm/annotated-maps/values-demo.yaml).

The local loop is `make kind-up` once, then `make deploy` (build, `kind load`,
`helm upgrade --install`). **CI runs that same `make deploy` target**, so image
tags and the install command live in exactly one place and cannot drift.

### Terraform — two stacks, deliberately split

- **[foundation/](../deploy/terraform/foundation/)** — persistent and free: the
  S3 state bucket, the GitHub OIDC provider, the read-only CI role and the
  deployer role, the IAM permissions boundary, an SNS topic, and a $10/month
  budget alarm.
- **[demo/](../deploy/terraform/demo/)** — ephemeral: a VPC across 2
  availability zones with a **single NAT gateway** as an explicit cost decision,
  an **EKS (Elastic Kubernetes Service)** cluster on 2 × `t3.medium` on-demand
  nodes, ECR, and **IRSA (IAM Roles for Service Accounts)**.

Community modules handle the VPC and EKS, and
[network.tf](../deploy/terraform/demo/network.tf) states the reasoning outright:
*"the subnet arithmetic isn't the exhibit — the IAM files are."* State lives in
S3 using Terraform 1.10+'s **native lockfile — no DynamoDB table**.

### The pipeline

[.github/workflows/demo-pipeline.yml](../.github/workflows/demo-pipeline.yml):

```
provision -> images -> deploy -> e2e -> destroy
                                          \-> alert-teardown-issue (AWS-independent)
                                          \-> alert-teardown-sns
```

- **images** — builds, then a **Trivy gate on CRITICAL *and* fixable findings**
  (`exit-code: 1`), then software bills of materials, and only then retags and
  pushes. A vulnerable image never reaches the registry.
- **deploy** — creates a per-run Neon branch, then installs the chart and runs a
  gating smoke test.
- **e2e** — Playwright against the **live load-balancer URL**, uploading
  screenshots `if: always()`, green or red.
- **destroy** — `if: always() && needs.provision.result != 'skipped'`, with
  `concurrency: cancel-in-progress: false` so a teardown is never cancelled, and
  `timeout-minutes` on every job.

### The infrastructure path in CI

In [ci.yml](../.github/workflows/ci.yml), `infra-plan` runs only on pull requests
that actually touch `deploy/terraform/`, inside a protected `aws-plan` GitHub
Environment with a **required reviewer** — so even a fork's pull request *pauses
for human approval before any OIDC token is issued*. The CI role's trust policy
accepts only the `...:environment:aws-plan` subject, and the role is read-only:
it can plan, never apply.

### What you might get wrong

- **Nothing is running on AWS right now, and that is the design.** The always-on
  demo is **Render plus Neon**. EKS is ephemeral: roughly $0.20–0.30 per full
  lifecycle run against roughly $180/month for an equivalent always-on
  environment. Do not say "deployed on Kubernetes in production." Say: *the
  chart installs on kind and passes `helm test` on every pull request, and the
  pipeline proves it on real EKS behind a load balancer on demand.*
- **All four roadmap milestones are shipped.** Nothing in
  [ROADMAP.md](../ROADMAP.md) is still "planned."
- **Disclose the deploy role before anyone asks.**
  [ADR-0010](adr/0010-pipeline-apply-role.md) states plainly that the pipeline's
  apply role is **AdministratorAccess-equivalent within the demo account**, and
  that the `annotated-maps-*` prefix is a blast-radius guard, *not* a security
  boundary against a malicious principal.
  [ADR-0012](adr/0012-deployer-permissions-boundary.md) then closed the
  escalation path with a permissions boundary. Volunteering this reads as
  maturity; being caught on it does not.
- **The cost figures are estimates from resource-hours, not Cost Explorer** —
  the docs say so explicitly. Match that hedge.
- **The cluster runs EKS 1.33, not the latest**, and
  [eks.tf](../deploy/terraform/demo/eks.tf) explains the choice: staying inside
  the Terraform module's current major version.

---

## 5. Verification and quality discipline

### The suites

| Layer | Roughly | Where |
|---|---|---|
| Backend unit and integration | 190 test functions | [core/tests/](../backend/core/tests/), [maps/tests/](../backend/maps/tests/) — pytest against a **real PostGIS service container**, not SQLite |
| Property-based | 5 invariants | [test_properties.py](../backend/core/tests/visibility/test_properties.py) — Hypothesis over the visibility engine |
| Frontend unit | ~106 cases | Vitest, colocated `*.test.tsx` |
| End-to-end | 28 Playwright tests | [e2e/](../frontend/e2e/) local, [e2e-prod/](../frontend/e2e-prod/) production-build guards, [e2e-alb/](../frontend/e2e-alb/) live load balancer |
| Helm | 26 template unit tests | [helm tests/](../deploy/helm/annotated-maps/tests/) — `helm unittest`, `kubeconform`, and lint across all three value sets |
| Alert rules | promtool | `promtool test rules` — **the alert rules have unit tests** |

### The gates that are not tests

- **[check_workflow_triggers.py](../.github/scripts/check_workflow_triggers.py)**
  fails the build if any workflow pairs `pull_request_target` with the
  `aws-deploy` environment. A human invariant from an ADR, turned mechanical.
- **[check_pr_body.py](../.github/scripts/check_pr_body.py)** requires every
  pull-request body to carry `## Summary`, `## Provenance`, `## Reasoning`,
  `## Testing`, and `## Risk & rollback` with real content — template comments
  do not count.
- **Docs have tests** ([ADR-0011](adr/0011-documentation-accuracy-practice.md)).
  [check_doc_links.py](../.github/scripts/check_doc_links.py) verifies every
  internal link and anchor;
  [check_doc_facts.py](../.github/scripts/check_doc_facts.py) verifies
  **registered facts** — a claim in prose annotated with the command that proves
  it and the expected output. Change the number in prose without changing the
  annotation, or the reverse, and CI fails. **The checkers themselves have unit
  tests.** A weekly scheduled run files an issue rather than reddening a pull
  request, and a `Docs-Checks-Override:` escape hatch *defers* rather than
  erases.
- **Linters are pinned**, and [ci.yml](../.github/workflows/ci.yml) explains why
  for shellcheck: version 0.11.0 dropped SC2015 from its defaults, so "green
  locally" did not mean "green in CI" until the version was pinned.

### The honesty artifact

[lessons-learned.md](lessons-learned.md) records 25 bugs, **each naming how it
was found**. By attribution: roughly 13 from live deployment, live runs, or live
verification; 7 from code review, several of them adversarial; 2 from CI; and the
rest from design, from the Trivy gate firing for real, and from *reading a green
run's own artifact*. **None came from unit tests.**

### What you might get wrong

- **"Zero caught by unit tests" needs the right framing.** It is not that the
  tests are theater — it is that unit tests catch *regressions*, while every
  *novel* bug came from running the thing for real or from a human reading the
  diff. The rule it produced is the quotable part: **a green run is not
  evidence; the artifact is.**
- **The AWS pipeline does not run on pull requests.** Only `infra-plan` touches
  AWS from CI, read-only and behind a required reviewer. The full pipeline is
  `workflow_dispatch` plus a monthly schedule.
- **`e2e-prod` runs against `vite preview`, not the deployed site.** Be precise
  about which environment each suite hits.

---

## The four things worth volunteering

**1. The visibility engine is pure, small, and fails closed on every path.**
No Django, no I/O, exhaustively unit-testable, with Hypothesis proving the
invariants rather than examples suggesting them. Every error path in the
row-to-rule mapping returns `Private()`, so a corrupt rule can only *hide*,
never *expose*. And denied content is never serialized at all — hidden sections
are dropped from the payload and a fully hidden note is omitted from the list,
so the API cannot leak what it never puts in the response. That is the
difference between filtering a response and never building one. The layering
argument — pure core, persistence bridge, request edge, each depending only
inward — transfers to any per-audience filtering problem.

**2. Guaranteed teardown, proven by failure rather than argued.**
Three of five live pipeline runs went red, and all five tore themselves down to
zero, unattended — including one that failed with a live cluster and two nodes
already running. The sweep read zero every time. The detail a senior engineer
notices: teardown failure opens a **GitHub issue** from a job with no AWS
dependency at all, because if AWS credentials are what broke, an SNS alert
cannot tell you.

**3. The documentation-accuracy practice — docs have tests.**
Load-bearing numeric claims carry a machine-checkable annotation (the command
plus its expected output), enforced on every pull request, with a weekly drift
job and an override that defers rather than erases. It is the direct answer to
*"how do you keep generated prose from drifting into fiction?"* — the same way
you keep code honest: make the claim executable.

**4. A CI gate born from a fix that turned out to be wrong.**
A ticket said a deployment-branch policy would stop a future
`pull_request_target` job handing a fork the AWS deploy role. Acting on it
revealed the premise was false: `pull_request_target` runs *in the context of
the default branch*, so its ref **is** `main` and a `main`-only policy admits
it. No OIDC scoping helps, because the event is designed to look like `main`.
So the invariant became a permanent CI gate instead — **and the gate was
verified by deliberately writing the forbidden workflow and watching it fail.**
That last clause is the point: a check you have not watched fail is not yet
evidence that it can.

*A fifth, in reserve:* optimistic concurrency resolved in the database —
`UPDATE ... WHERE version = expected`, loser updates zero rows, 409. No
read-then-write, no lock.

---

## Glossary

| Acronym | Expansion | In this repo |
|---|---|---|
| **ADR** | Architecture Decision Record | [docs/adr/](adr/) — decisions with alternatives and consequences |
| **ALB** | Application Load Balancer (AWS) | Fronts the ephemeral EKS deployment |
| **CVE** | Common Vulnerabilities and Exposures | The Trivy gate blocks CRITICAL, fixable CVEs before an image is pushed |
| **DRF** | Django REST Framework | *Not* used — the API is Django Ninja ([ADR-0002](adr/0002-tech-stack.md)) |
| **ECR** | Elastic Container Registry (AWS) | Holds the pipeline's scanned images |
| **EKS** | Elastic Kubernetes Service (AWS) | The ephemeral demo cluster, version 1.33 |
| **HPA** | HorizontalPodAutoscaler | 2 to 4 API pods at 70% CPU |
| **IRSA** | IAM Roles for Service Accounts | Gives the load-balancer controller — and only it — AWS permissions |
| **OIDC** | OpenID Connect | GitHub-to-AWS federation; no long-lived keys stored anywhere |
| **OTLP** | OpenTelemetry Protocol | The wire format exporting traces, metrics, and logs to Grafana Cloud |
| **PDB** | PodDisruptionBudget | Keeps at least one API pod up during voluntary disruption |
| **RLS** | Row-Level Security (Postgres) | Deliberately deferred; `tenant_id` is threaded today ([ADR-0005](adr/0005-rls-tenant-isolation-deferred.md)) |
| **SPA** | Single-Page Application | The Vite/TypeScript frontend, served as a static site |
