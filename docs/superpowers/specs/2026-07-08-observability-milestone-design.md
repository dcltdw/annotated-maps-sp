# Milestone 2 — Observability — Design

- **Date:** 2026-07-08
- **Status:** Approved design, pending implementation plans
- **Slice:** Roadmap Milestone 2 (board card "Milestone 2 — Observability")
- **Roadmap contract (ROADMAP.md):** a public dashboard link in the README
  showing live-demo traffic, plus dashboards-as-code and SLOs in-repo.

## Context

Phase 0 laid the observability seam: [core/middleware.py](../../backend/core/middleware.py)
binds `request_id` (honoring inbound `X-Request-ID`) plus tenant/user IDs into
structlog contextvars, and [core/logging.py](../../backend/core/logging.py)
renders JSON log lines. Milestone 1 shipped the Helm chart the in-cluster
monitoring stack plugs into. This milestone makes the running system
*visible*: instrument once with OpenTelemetry, then light up two destinations
— Grafana Cloud (free tier) over the live Render demo, and a
kube-prometheus-stack on the local kind cluster.

Decisions locked during brainstorming:

1. **Grafana Cloud account arrives at a late, explicit checkpoint** (a user
   action, like M1's tooling install). Everything is built and verified
   local-first; the cloud wiring is a config swap at the end.
2. **All three signals ship:** traces, metrics, AND logs (via OTLP) — the
   flagship demo is clicking a trace and jumping to its log lines in one UI.
3. **Two PRs, local-first:** PR-A = instrumentation core + local verification
   harness + all of Tier 2 (zero external dependencies). PR-B = Tier 1
   Grafana Cloud wiring (gated on the account checkpoint).
4. **Export architecture = direct OTLP from the app** (Approach A below).

## Goals

1. One instrumentation layer, vendor-neutral: the same app config points at a
   local collector, Grafana Cloud, or any OTLP backend by changing env vars.
2. Trace ⇄ log ⇄ request correlation from any starting point: spans carry
   `request_id`/tenant/user attributes; every JSON log line carries
   `trace_id`/`span_id`.
3. In-cluster monitoring on the M1 chart: Prometheus scrape, dashboards and
   alert rules as code, two written SLOs with burn-rate alerts and a runbook.
4. A public Grafana Cloud dashboard over real demo traffic, linked from the
   README (the roadmap's "done means").
5. Everything *we build* is CI-guarded; manual steps are limited to
   third-party-UI verification (enumerated in §9).

## Non-goals (named, mapped)

- **No OpenTelemetry Collector deployment** — the correct EKS-era topology
  (collector DaemonSet) is Milestone 3's concern; ADR-0008 names it.
- **No vendor agents** (Grafana Alloy, Datadog SDK) — rejected in ADR-0008;
  they undercut the vendor-neutrality story this milestone demonstrates.
- **No alert delivery wiring** (PagerDuty/email) — alerts render in Grafana.
- **No frontend/browser tracing** — possible later polish.
- **No telemetry from the reaper cron or migrate hook** — API service only
  (and, per the PR-#42 lesson, Tier 1 env vars go on the API Render service
  only, so no other service gains new required env).

## Design

### 1. Export architecture (ADR-0008)

**Chosen: direct OTLP/HTTP export from the Django process.** Endpoint and
auth are pure env config (`OTEL_EXPORTER_OTLP_ENDPOINT`,
`OTEL_EXPORTER_OTLP_HEADERS`); batching/retry live in the SDK's batch
processors. No new infrastructure on Render (free tier cannot run sidecars);
the local harness points the *same* env vars at a local collector — the
vendor-neutrality argument made demonstrable.

Alternatives recorded in `docs/adr/0008-opentelemetry-over-vendor-sdks.md`:
an app→collector→backends topology (production-correct at fleet scale;
deferred to M3/EKS), and vendor agents/SDKs (rejected — one-instrumentation-
many-backends is the point; also records the deliberate **django-prometheus +
OTel duality**: pull-based scrape is the Kubernetes-native pattern for
cluster monitoring, OTLP push for SaaS; both are fed by one app).

Known trade-off (named): in-process export means a backend outage sheds
telemetry after the SDK buffer fills — acceptable for a demo.

### 2. Instrumentation core (PR-A)

New `backend/annotated_maps/telemetry.py`, initialized from `settings.py`,
**env-gated by `OTEL_ENABLED` (default `false`)** — disabled means zero OTel
processors/handlers installed and log output byte-identical to today's.

When enabled:
- **Traces:** Django + psycopg auto-instrumentation (request spans, DB
  spans). A span processor stamps `request_id`, tenant, and user IDs from the
  structlog contextvars onto each request span.
- **Log join (both directions):** a structlog processor injects the active
  `trace_id`/`span_id` into every JSON line; an OTel `LoggingHandler` bridge
  ships the same records as OTLP logs.
- **Metrics:** OTLP metrics from the SDK (request rate/duration via the
  Django instrumentation).
- Service identity via `OTEL_SERVICE_NAME=annotated-maps-api` +
  deploy-environment resource attribute (`render` / `kind` / `local`).

### 3. Local verification harness (PR-A)

`deploy/observability/docker-compose.yml`: otel-collector, Grafana OSS,
Tempo, Prometheus, Loki, with provisioned datasources. `make obs-up` /
`obs-down` targets. `scripts/synthetic_traffic.py` drives the API's public
endpoints (maps, notes as several personas, health) to generate realistic
telemetry. Acceptance: backend running with `OTEL_ENABLED=true` pointed at
localhost → open local Grafana → find the trace → click through to its log
lines. **Zero external accounts, zero public traffic.** The same script later
verifies the live deploy (PR-B).

### 4. Tier 2 — in-cluster stack (PR-A)

- **`/metrics` via django-prometheus** (middleware + urls), **cluster-internal
  by construction**: the endpoint mounts at root (`/metrics`), NOT under
  `/api` — and the public Ingress routes only `/api` to the API service
  (everything else goes to the web tier), so no public route can reach it.
  The guarantee is structural, pinned by tests (§9.1 asserts `/metrics` is
  not served under any `/api/*` path; §9.3's chart test asserts the Ingress
  routes only `/api` to the API service).
- **kube-prometheus-stack via `make monitoring-up`** — a separate Helm
  release (like ingress-nginx/metrics-server), NOT a dependency of the app
  chart; the app chart stays lean.
- **M1 chart additions (values-gated `monitoring.enabled`, default off so
  the chart installs unchanged without the CRDs):** a `ServiceMonitor`
  scraping the API service, and a `PrometheusRule` with the two burn-rate
  alerts.
- **Dashboards as code:** JSON under `deploy/observability/dashboards/`
  (one API-overview dashboard: rate/errors/duration + SLO panels), loaded
  in-cluster via the grafana-sidecar ConfigMap-label pattern, and the same
  JSON imported to Grafana Cloud in PR-B — one dashboard, two homes.
- **SLOs in `docs/slos.md`:** availability — 99.5% of API requests non-5xx
  over 30 days; latency — 99% of API requests complete < 500 ms over 30
  days. Each SLO: definition, the PromQL behind it, its burn-rate alert, and
  a runbook section (alert fired → the three commands to run:
  `kubectl get pods`, `logs`, the dashboard link).

### 5. Tier 1 — Grafana Cloud wiring (PR-B)

- **User checkpoint (explicit, at PR-B start):** create the Grafana Cloud
  free-tier account; obtain the OTLP gateway endpoint + token; set them on
  the **annotated-maps-api Render service only** (env vars `sync: false` in
  render.yaml, values set in the dashboard) plus `OTEL_ENABLED=true`.
- Import the dashboard JSON; enable Grafana Cloud **public dashboard** sharing;
  link it from README ("see the live demo's telemetry") and the ROADMAP
  Milestone 2 proof column; flip the roadmap row to ✅.
- Verification: `scripts/synthetic_traffic.py --base-url https://annotated-maps-api.onrender.com`
  then confirm traces/metrics/logs in Grafana Cloud — plus organic demo
  traffic thereafter.

### 6. Repo layout

```
backend/annotated_maps/telemetry.py     OTel setup (env-gated)
backend/core/logging.py                 + trace-context structlog processor
backend/annotated_maps/settings.py      OTEL_* settings, /metrics gating, init hook
deploy/observability/docker-compose.yml local Grafana/Tempo/Prometheus/Loki/collector
deploy/observability/dashboards/api-overview.json
deploy/observability/alerts/            PrometheusRule source + promtool test cases
deploy/helm/annotated-maps/templates/servicemonitor.yaml   (monitoring.enabled)
deploy/helm/annotated-maps/templates/prometheusrule.yaml   (monitoring.enabled)
scripts/synthetic_traffic.py
docs/slos.md
docs/adr/0008-opentelemetry-over-vendor-sdks.md
Makefile                                + obs-up/obs-down/monitoring-up targets
```

### 7. Dependencies

`opentelemetry-sdk`, `opentelemetry-instrumentation-django`,
`opentelemetry-instrumentation-psycopg` (or psycopg2 variant matching the
driver), `opentelemetry-exporter-otlp-proto-http`, `django-prometheus`.
All added to `pyproject.toml` as main dependencies (they are inert when
`OTEL_ENABLED=false`; django-prometheus middleware is cheap). No frontend
dependency changes.

### 8. Failure modes (named)

- OTLP endpoint unreachable → SDK buffers then sheds; app latency unaffected
  (batch processors are off-thread). Telemetry loss is acceptable-by-design
  for the demo; the spec says so.
- `OTEL_ENABLED` unset/false anywhere (tests, CI, current prod) → behavior
  identical to today, guaranteed by test (§9.1).
- kube-prometheus-stack absent but `monitoring.enabled=true` → CRD objects
  fail to apply; default is therefore `false`, and `make monitoring-up` docs
  the order. Chart unittest covers both gate positions.

### 9. Testing (the robustness matrix)

**9.1 Pytest layer (PR-A, existing backend CI job; in-memory exporters — no
network, no docker):**
1. Request via Django test client with OTel enabled → the captured span's
   `trace_id` appears in the emitted JSON log line, and the span carries
   `request_id`/tenant/user attributes (the join, tested from both ends).
2. `OTEL_ENABLED=false` (default) → no OTel processors/handlers installed;
   log output byte-identical to today's (zero-overhead claim pinned).
3. **OTLP wire test:** in-process mock OTLP/HTTP receiver; real exporter
   pointed at it; force-flush; assert protobuf payloads for traces, metrics,
   and logs arrive (proves the export mechanics that would break against
   Grafana Cloud, with no external service).
4. `/metrics` serves 200 with expected metric families in the internal
   context, and is NOT reachable through any public route (gating test).

**9.2 Alert-rule unit tests (PR-A, CI):** `promtool check rules` for syntax
plus `promtool test rules` cases with synthetic series — error rate above
the SLO threshold fires the availability burn alert; below stays green;
same pair for the latency alert. This pins the SLO doc and the PromQL to
each other. Dashboard JSON gets a parse gate.

**9.3 Chart layer (existing `helm` CI job):** helm-unittest — ServiceMonitor
and PrometheusRule render when `monitoring.enabled=true` and are absent when
false; an assertion that the Ingress routes ONLY `/api` to the API service
(the structural half of the /metrics guarantee); kubeconform as before.
**The live `helm-install` job gains one step:** port-forward the API service
and curl `/metrics` (proves the scrape endpoint live in-cluster).

**9.4 Deliberately manual (small, enumerated):** the local-Grafana
click-through (trace→logs UX — automating it would test Grafana, not our
code) and the final Grafana Cloud end-to-end after the account checkpoint
(external SaaS; our side is covered by 9.1's wire test).

### 10. Tracking

Board card "Milestone 2 — Observability" → In Progress at spec time; PR-A
and PR-B each get the repo's rigor-section PR bodies; ROADMAP row flips ✅ in
PR-B with proof links (public dashboard, dashboards dir, SLO doc, ADR-0008).

## Risks & mitigations

- **Grafana Cloud free-tier limits/changes:** demo volume is far below the
  free tier; if terms change, the ADR's whole point is that the exporter
  endpoint is swappable.
- **OTel Python API churn:** pin versions in pyproject; the wire test
  catches breakage on upgrade.
- **kube-prometheus-stack weight on kind:** it's heavy (~1 GB RAM); it's
  opt-in via `make monitoring-up`, not part of `make kind-up`, so M1's
  lightweight loop is unchanged.
- **Account checkpoint stalls PR-B:** by design — PR-A carries all the
  engineering and merges independently.

## Testing summary

Backend pytest (new §9.1 suite + existing 181 green with OTel off);
promtool check + rule unit tests; helm unittest + kubeconform + extended
live smoke; manual: local-Grafana click-through, Grafana Cloud E2E post-
checkpoint.
