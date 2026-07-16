# Production-Engineering Roadmap

Annotated Maps is a working, deployed product — a multi-tenant map-annotation platform ([Django](https://www.djangoproject.com/)/[PostGIS](https://postgis.net/) backend, Vite/TypeScript frontend) with a [live demo](https://annotated-maps-web.onrender.com/) you can use right now. This roadmap tracks the work of taking it from "solid deployed application" to **production-grade**: Kubernetes and Helm, AWS infrastructure as code, observability, and automated deployment pipelines.

**How to read this:** the table below is the summary; each milestone has a section with the reasoning and trade-offs. Every completed milestone links to verifiable evidence — a merged PR, a public CI run, a dashboard, an architecture decision record — not just a claim.

**All four milestones are shipped.** The capstone is a [one-button pipeline](docs/m4-pipeline.md) that builds the whole AWS environment from nothing, proves the app works against its live URL, and destroys it again — in 35 minutes, for an estimated ~$0.25 (from resource-hours; not yet confirmed via Cost Explorer), with the teardown guaranteed. Everything below is done and evidenced; what follows the roadmap is [what I deliberately didn't build](#what-i-deliberately-didnt-build) and why.

## Status

| Milestone | Technologies & practices | Status | Proof |
|---|---|---|---|
| [CI quality gates](#phase-0-already-shipped) | **GitHub Actions**, lint/type/test/e2e gates, **Playwright** | ✅ Shipped | [ci.yml](.github/workflows/ci.yml) · [runs](https://github.com/dcltdw/annotated-maps-sp/actions) |
| [Containerized backend](#phase-0-already-shipped) | **Docker**, **docker-compose**, **PostGIS** | ✅ Shipped | [Dockerfile](backend/Dockerfile) · [docker-compose.yml](backend/docker-compose.yml) |
| [Declarative cloud deployment](#phase-0-already-shipped) | Blueprint-as-code, zero-downtime migrations, cron jobs | ✅ Shipped | [render.yaml](render.yaml) · [live demo](https://annotated-maps-web.onrender.com/) |
| [Architecture as a written practice](#phase-0-already-shipped) | **ADRs**, design specs, production-concern triage | ✅ Shipped | [ADRs](docs/adr/) · [production lenses](docs/architecture/production-lenses.md) · [specs](docs/superpowers/specs/) |
| [1 — Kubernetes & Helm](#milestone-1--kubernetes--helm) | **Kubernetes**, **Helm**, probes, HPA, CronJobs, **kind** | ✅ Shipped | [chart](deploy/helm/annotated-maps/) · [ADR-0007](docs/adr/0007-migrations-via-helm-hooks.md) · [primer](docs/kubernetes-primer.md) · [CI runs](https://github.com/dcltdw/annotated-maps-sp/actions) |
| [2 — Observability](#milestone-2--observability) | **OpenTelemetry**, **Grafana**, **Prometheus**, SLOs | ✅ Shipped | [public dashboard](https://friendlynewt1033.grafana.net/public-dashboards/20407e8eaf204a899c3feb0af005935d) · [dashboards-as-code](deploy/observability/dashboards/) · [SLOs](docs/slos.md) · [ADR-0008](docs/adr/0008-opentelemetry-over-vendor-sdks.md) |
| [3 — AWS infrastructure as code](#milestone-3--aws-infrastructure-as-code) | **Terraform**, **AWS EKS**, **IAM**/IRSA, **VPC** networking, ECR | ✅ Shipped | [demo run](docs/m3-demo-run.md) · [terraform](deploy/terraform/) · [ADR-0009](docs/adr/0009-eks-over-ecs.md) · [primer](docs/aws-primer.md) |
| [4 — One-button ephemeral environment](#milestone-4--one-button-ephemeral-environment) | Automated deployments, infrastructure pipelines, testing gates | ✅ Shipped | [pipeline run](docs/m4-pipeline.md) · [workflow](.github/workflows/demo-pipeline.yml) · [ADR-0010](docs/adr/0010-pipeline-apply-role.md) |

Statuses: ✅ shipped · 🚧 in progress · 📋 planned.

---

## Phase 0 — already shipped

The foundation the roadmap builds on. All of it is live in this repo today.

**CI quality gates.** Every push and pull request runs the CI quality-gate suite in [GitHub Actions](.github/workflows/ci.yml):

1. Backend lint, format, type-checking, and tests (`ruff`, `mypy`, `pytest`) against a real PostGIS service container
2. Frontend lint, unit tests, and build
3. Playwright end-to-end tests, including production-build guards
4. Helm chart lint + template unit tests, plus a full chart install on `kind` (added in Milestone 1)
5. Terraform `fmt`/`validate`/`tflint` and workflow lint (added in Milestones 3–4)

On pull requests, a PR-rigor check on the description runs too. Nothing merges red.

**Containerized backend.** The Django/Gunicorn backend builds from a [Dockerfile](backend/Dockerfile) that is the same image used in production; local development runs PostGIS via [docker-compose](backend/docker-compose.yml).

**Declarative cloud deployment.** The whole production environment is described in one committed file — [render.yaml](render.yaml) provisions the API service (with health checks and a pre-deploy migration step), the static frontend, and a nightly cron job that reaps expired sandbox data. Nothing about the deployment lives only in a dashboard.

**Architecture as a written practice.** Cross-cutting production concerns were triaged on day one in [production-lenses.md](docs/architecture/production-lenses.md) — deciding explicitly what to build now, what to leave a seam for, and what to defer. Significant decisions are recorded as [ADRs](docs/adr/) (PostGIS for geometry, expand-contract migrations, deferred RLS tenant isolation, …), and every feature slice starts from a written [design spec](docs/superpowers/specs/). Several of the seams laid down then — structured logs with request/tenant IDs, a stateless app tier, API versioning — are exactly what milestones 1–3 build on.

---

## Milestone 1 — Kubernetes & Helm

**Plain English:** package the application so it can run on Kubernetes — the way most companies actually operate services — and run it locally that way, every day, for free.

**The work:** a Helm chart covering the full application: the API as a Deployment with liveness/readiness probes, database migrations as a pre-upgrade hook Job (today's `predeploy.sh`), the nightly reaper as a native CronJob, Ingress, a HorizontalPodAutoscaler, and a PodDisruptionBudget, with separate values files per environment. A local [kind](https://kind.sigs.k8s.io/) cluster runs the chart end-to-end, so the Kubernetes workflow is exercised continuously rather than saved for demos.

**Trade-off considerations:** mapping an app with a deploy-time migration step onto Helm's upgrade lifecycle — what belongs in a hook Job versus an init container, and how that interacts with rollbacks.

**Done means:** shipped — the chart is in-repo, `helm install` brings up the full app on kind, and CI lints and template-tests the chart on every push.

## Milestone 2 — Observability

**Plain English:** you shouldn't have to trust that the live demo works — you should be able to see it. Real dashboards over real traffic, publicly linkable.

**The work:** two tiers. First, instrument Django with **OpenTelemetry** (traces, metrics, and logs — the logs joined to the structured request/tenant IDs from the Phase-0 seam, so a trace links straight to its log lines) and export from the live Render deployment to **Grafana Cloud's** free tier: always-on dashboards at zero hosting cost. Second, an in-cluster stack — **kube-prometheus-stack** installed by the Milestone 1 chart, `/metrics` via django-prometheus, dashboards and alert rules committed as code, and two written SLOs (API latency, error rate) with a short runbook.

**Trade-off considerations:** why OpenTelemetry rather than a vendor SDK — instrumenting once against the vendor-neutral standard makes Grafana/Datadog/Honeycomb a config change, not a re-instrumentation. Proven, not just asserted: the same app config points at a local collector, the in-cluster Prometheus, or Grafana Cloud by changing one env var.

**Done:** a [public dashboard](https://friendlynewt1033.grafana.net/public-dashboards/20407e8eaf204a899c3feb0af005935d) showing live-demo request rate, latency, and error ratio; [dashboards-as-code](deploy/observability/dashboards/) and [SLOs with a runbook](docs/slos.md) in-repo; and [ADR-0008](docs/adr/0008-opentelemetry-over-vendor-sdks.md) recording the vendor-neutral decision.

## Milestone 3 — AWS infrastructure as code

**Plain English:** a complete, working AWS production environment defined entirely in code — spun up on demand for a few dollars, exercised, and destroyed. Rent the infrastructure for an hour for a known demo, instead of paying for a cluster that sits idle.

**The work:** **Terraform** (modules, remote state in S3 with locking) defining a VPC with public/private subnets, an **EKS** cluster with a small managed node group, ECR for images, and an ALB via the aws-load-balancer-controller. The IAM story is the centerpiece: **IRSA** (IAM Roles for Service Accounts) gives pods least-privilege credentials, and GitHub Actions authenticates to AWS via **OIDC federation — no long-lived keys stored anywhere**. The database stays on Neon (a branch per environment) so the ephemeral environment boots in minutes. Cost guardrails — budget alarms, tagging, `make demo-up` / `make demo-down` — are part of the deliverable, and screenshots/recordings document each run since the environment is intentionally not left running.

**Trade-off considerations:** EKS versus ECS (an ADR will record the reasoning), and the economics of an ephemeral environment versus an always-on one at this project's scale.

**Done:** `make demo-up` provisioned a working, load-balanced deployment on EKS — the app served real traffic through an ALB ([evidence, with a screenshot of it running](docs/m3-demo-run.md)) — and `make demo-down` destroyed all 61 resources back to zero (swept clean). Static checks (fmt/validate/tflint) run on every infra PR; the authenticated `terraform plan` runs fork-safely on PRs via a protected GitHub Environment (OIDC, required-reviewer gated); [ADR-0009](docs/adr/0009-eks-over-ecs.md) published. The live run also caught two real bugs the tests had missed ([lessons-learned](docs/lessons-learned.md)). Not left running by design — the durable artifact is the evidence, not an always-on service.

## Milestone 4 — One-button ephemeral environment

**Plain English:** the capstone — a single button that builds the entire AWS environment from nothing, deploys the app, proves it works with automated tests, and tears it all down. Every run leaves a public, verifiable record of the full lifecycle.

**The work:** one `workflow_dispatch` GitHub Actions pipeline chaining everything: Terraform provisions the Milestone 3 environment → the image builds and pushes to ECR (with a Trivy vulnerability scan and SBOM as gates) → Helm deploys the Milestone 1 chart → Playwright smoke tests run against the live URL and upload screenshots as artifacts → Terraform destroys everything, with the destroy step guaranteed to run even when a prior step fails.

**Trade-off considerations:** making infrastructure pipelines safe to fail — ensuring a red run can't strand billable resources.

**Done:** one dispatch builds the environment from nothing, deploys, tests against the live URL, and destroys everything — [a green public run](https://github.com/dcltdw/annotated-maps-sp/actions/runs/29447574490) in 35 minutes, with the Playwright screenshot of the app running on EKS attached as an artifact ([evidence](docs/m4-pipeline.md)). Teardown is guaranteed by `if: always()` and was proven the hard way: **three of the five live runs went red, and all five tore themselves down to zero** unattended — including one that failed with a cluster and two nodes already up. The Trivy gate earned its place by failing a real CRITICAL CVE and blocking the push. The live runs caught four bugs that static analysis and code review had missed ([lessons-learned](docs/lessons-learned.md)); [ADR-0010](docs/adr/0010-pipeline-apply-role.md) records the apply-role security model, including an honest disclosure of what that role can do in the demo account. Runs monthly on a schedule to surface drift. Cost: an estimated ~$0.20–0.30 per run (from resource-hours; not yet confirmed via Cost Explorer), under a $10/month budget alarm.

---

## What I deliberately didn't build

Each of these was considered and rejected for cause, not skipped out of unfamiliarity:

- **Datadog** — proprietary and priced for companies, not portfolios. OpenTelemetry instrumentation is the vendor-neutral 80% of onboarding *any* APM vendor; the remaining 20% is configuration.
- **A parallel ECS implementation** — ECS and EKS solve the same problem. Building both would duplicate effort without new insight; the EKS-vs-ECS ADR covers the decision-making, which is the more informative artifact.
- **An always-on EKS cluster** — ~$75+/month for a control plane serving a portfolio demo is poor cost engineering. The ephemeral pipeline (Milestone 4) proves the same capability and adds a harder one: infrastructure that is safe to create and destroy on demand.
- **Splitting the monolith into microservices** — a monolith at this scale is the correct architecture. A well-operated monolith on Kubernetes is credible; a speculative microservice split to justify the platform is an unnecessary design choice.
- **Service mesh, multi-region, Karpenter** — capability theater at this scale. The [production-lenses document](docs/architecture/production-lenses.md) records where each would earn its place as the system grows.
