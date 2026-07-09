# Milestone 2 PR-B — Grafana Cloud Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Point the live Render deployment's already-shipped OTel instrumentation at Grafana Cloud, publish a public dashboard, and flip the roadmap milestone — the small config-and-docs tail of M2.

**Architecture:** No code changes. PR-A's `telemetry.py` reads `OTEL_EXPORTER_OTLP_ENDPOINT`/`_HEADERS` from env; this PR declares those vars in render.yaml (values set by hand in the Render dashboard), imports PR-A's dashboard JSON into Grafana Cloud, and updates docs.

**Tech Stack:** Grafana Cloud free tier (OTLP gateway), Render env config.

**Spec:** `docs/superpowers/specs/2026-07-08-observability-milestone-design.md` §5. **Prerequisite: PR-A merged** (verify: `backend/annotated_maps/telemetry.py` exists on main and `deploy/helm/annotated-maps/files/dashboards/api-overview.json` exists — STOP if not).

## Global Constraints

- Env vars go on the **annotated-maps-api Render service ONLY** (not the reaper, not the web static site) — the PR-#42 lesson: no new required env on services that don't need it. The reaper never sets `OTEL_ENABLED`, so it keeps booting exactly as today.
- Secrets (`OTEL_EXPORTER_OTLP_HEADERS` carries the Grafana Cloud token) are `sync: false` in render.yaml and set by hand — never committed.
- Public dashboard must not expose anything sensitive: it reads aggregate metrics/traces of a public demo — confirm no log panel with raw log lines is on the PUBLIC dashboard (traces/logs stay behind the account; the public view is the metrics overview).
- Repo conventions: rigor-section PR body; `Co-Authored-By` trailer.

---

### Task 1: USER CHECKPOINT — Grafana Cloud account + Render env (STOP; user action)

**Files:** none.

This task is performed by the USER (the agent stops and asks). Checklist to hand them:

- [ ] 1. Create a free Grafana Cloud account (grafana.com → Free tier). In the portal, open the stack's **OpenTelemetry / OTLP** configuration page and note: the **OTLP endpoint** (looks like `https://otlp-gateway-<region>.grafana.net/otlp`) and generate an **API token** with metrics/traces/logs write scope. The page shows the ready-made header value `Authorization=Basic <base64 instance:token>` — copy it exactly.
- [ ] 2. In the Render dashboard → `annotated-maps-api` → Environment, add:
  - `OTEL_ENABLED` = `true`
  - `OTEL_EXPORTER_OTLP_ENDPOINT` = the OTLP endpoint from step 1
  - `OTEL_EXPORTER_OTLP_HEADERS` = the Authorization header value from step 1
  - `OTEL_SERVICE_NAME` = `annotated-maps-api`
  - `DEPLOY_ENV` = `render`
  (Render restarts the service on env save.)
- [ ] 3. Tell the agent "checkpoint done" (with the endpoint's region so docs can name it, token NOT shared in chat).

Verification that gate passed (agent runs): `python3 scripts/synthetic_traffic.py --base-url https://annotated-maps-api.onrender.com --loops 15` completes; user (or a Grafana screenshot) confirms traces/metrics/logs arriving in the Grafana Cloud stack. If nothing arrives within ~5 minutes: check Render logs for OTLP export warnings (bad token = 401s from the gateway, visible in stderr).

---

### Task 2: render.yaml declarations + Grafana Cloud dashboard

**Files:**
- Modify: `render.yaml` (annotated-maps-api envVars only)

- [ ] **Step 1:** In `render.yaml` under the `annotated-maps-api` service's `envVars`, append (values live in the dashboard; the blueprint declares them so a fresh blueprint sync doesn't drop observability):

```yaml
      - key: OTEL_ENABLED
        value: "true"
      - key: OTEL_SERVICE_NAME
        value: annotated-maps-api
      - key: DEPLOY_ENV
        value: render
      - key: OTEL_EXPORTER_OTLP_ENDPOINT
        sync: false   # Grafana Cloud OTLP gateway URL, set per-environment
      - key: OTEL_EXPORTER_OTLP_HEADERS
        sync: false   # Authorization header w/ Grafana Cloud token — SECRET
```

Validate YAML parses. Do NOT touch the reaper or web services.

- [ ] **Step 2 (user-assisted):** In Grafana Cloud: import `deploy/helm/annotated-maps/files/dashboards/api-overview.json` (Dashboards → Import → paste JSON; select the stack's Prometheus datasource). NOTE: the local dashboard queries django-prometheus metric names, which exist in-cluster; the Grafana Cloud stack receives OTel metrics (different names, e.g. `http_server_duration_*`). Duplicate the dashboard and retarget its four panels at the OTel metric names observed in the stack (the PR-A Task 2 report recorded the actual names) — panel titles and layout stay identical. Then Share → **Public dashboard** → enable, copy the public URL.
- [ ] **Step 3:** Run `python3 scripts/synthetic_traffic.py --base-url https://annotated-maps-api.onrender.com --loops 20`; confirm the public dashboard shows the traffic (user eyeballs or screenshots).
- [ ] **Step 4:** Commit:

```bash
git add render.yaml
git commit -m "feat(obs): declare OTel env on the API service for Grafana Cloud export"
```

---

### Task 3: README + ROADMAP + board

**Files:**
- Modify: `README.md`, `ROADMAP.md`

- [ ] **Step 1:** README — in the intro area (after the live-demo/roadmap lines), add one line: `**▶ [Live telemetry dashboard](<public-dashboard-url>)** — real traces and metrics from the demo, exported via OpenTelemetry to Grafana Cloud.` Use the actual public URL from Task 2.
- [ ] **Step 2:** ROADMAP — Milestone 2 table row `📋 Planned` → `✅ Shipped`; Proof cell → `[public dashboard](<url>) · [dashboards-as-code](deploy/helm/annotated-maps/files/dashboards/) · [SLOs](docs/slos.md) · [ADR-0008](docs/adr/0008-opentelemetry-over-vendor-sdks.md)`; "Done means" line to past tense. No other rows.
- [ ] **Step 3:** Commit; branch ready for the PR-B pull request (rigor sections). After merge: board card "Milestone 2 — Observability" → Done.

```bash
git add README.md ROADMAP.md
git commit -m "docs: public telemetry dashboard link; roadmap Milestone 2 shipped"
```
