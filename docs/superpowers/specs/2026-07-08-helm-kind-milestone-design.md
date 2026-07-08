# Milestone 1 — Kubernetes & Helm — Design

- **Date:** 2026-07-08
- **Status:** Approved design, pending implementation plan
- **Slice:** Roadmap Milestone 1 (board card "Milestone 1 — Kubernetes & Helm")
- **Roadmap contract (ROADMAP.md):** chart in-repo, `helm install` brings up the
  full app on kind, CI lints and template-tests the chart.

## Context

The app deploys today via a Render Blueprint ([render.yaml](../../render.yaml)):
a Docker web service (Django/Gunicorn), a static site (Vite build), and a cron
(the reaper), with `predeploy.sh` (migrate + seed refresh) run before each
deploy. This milestone packages the same application as a **Helm chart** that
runs end-to-end on a **local kind cluster** — the everyday-Kubernetes
foundation that Milestone 3 later deploys, unchanged, to ephemeral EKS.

Decisions locked during brainstorming:

1. **Everything in-cluster**: API + migration hook + reaper + a values-gated
   dev PostGIS + the frontend behind one Ingress.
2. **CI = static checks + a live kind install** on every PR.
3. **Workflow role = parity check**, not the daily dev loop: runserver/Vite
   stay for coding; `make kind-up / deploy / kind-down` bring up the parity
   environment.
4. **Migrations = Helm pre-upgrade hook Job** (Approach A; ADR-0007 records
   the alternatives).

## Goals

1. `make kind-up && make deploy` → working app at `http://localhost/` — pins,
   tour, personas, all of it — from nothing, on a laptop, free.
2. The deploy-time ordering guarantee (migrate before new code serves) is
   preserved in Kubernetes form, with the rollback story written down.
3. CI proves the chart both statically (lint/template/schema) and live
   (real kind install + smoke) on every PR.
4. A newcomer-oriented primer explains the stack and the daily commands, with
   pointers into this repo's files.

## Non-goals (named, mapped)

- **No registry pushes** (ECR/GHCR, scan, SBOM) — Milestone 4's pipeline.
- **No TLS/cert-manager** — TLS arrives with the ALB in Milestone 3.
- **No EKS-specific anything** — Milestone 3.
- **No Tilt/Skaffold dev-loop ergonomics** — decided against (workflow role is
  parity check, not primary environment).
- **No observability wiring** — Milestone 2.

## Design

### 1. Repo layout

```
deploy/helm/annotated-maps/
  Chart.yaml
  values.yaml                  defaults = local kind (dev secrets committed, postgres.enabled=true)
  values-prod.yaml             illustrative prod shape (postgres off, external DATABASE_URL, seed off)
  templates/
    _helpers.tpl
    secret.yaml                ONE shared Secret consumed by api + hook + reaper
    api-deployment.yaml   api-service.yaml
    web-deployment.yaml   web-service.yaml
    ingress.yaml
    migrate-hook-job.yaml
    reaper-cronjob.yaml
    hpa.yaml   pdb.yaml
    postgres-statefulset.yaml  postgres-service.yaml   (rendered only when postgres.enabled)
    tests/test-connection.yaml  # `helm test` pod: curls the API health endpoint
  tests/                       helm-unittest template tests
frontend/Dockerfile            NEW multi-stage image (node build → nginx)
frontend/nginx.conf            SPA fallback config for the image
deploy/kind/cluster.yaml       kind config: host ports 80/443 → ingress
Makefile                       kind-up / deploy / kind-down / helm-checks
docs/adr/0007-migrations-via-helm-hooks.md
docs/kubernetes-primer.md      NEW newcomer primer (see §9)
.github/workflows/ci.yml       + `helm` (static) and `helm-install` (live) jobs
```

Namespace `annotated-maps`, release name `annotated-maps`, installed with
`--create-namespace`.

### 2. API workload

- Deployment of the existing backend image (built from repo root with
  `backend/Dockerfile`), default **2 replicas**, port 8000.
- **Liveness AND readiness probe `GET /api/v1/health`** — deliberately DB-free,
  continuing the documented Render decision: restarts can't fix a down DB
  (liveness), and readiness-flapping during a Neon cold start would turn "DB
  briefly slow" into "entire service 503s". Trade-off recorded in the spec and
  primer.
- Resource requests 100m CPU / 256Mi (HPA requires requests); limits 500m/512Mi.
- **HPA**: min 2, max 4, target 70 % CPU. **PDB**: `minAvailable: 1`.
- Env: secrets (DJANGO_SECRET_KEY, DATABASE_URL, MOD_TOKEN) from the shared
  Secret; plain settings (SANDBOX_MODE, DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS,
  SECURE_SSL_REDIRECT=false locally) from values. Same-origin serving means
  **CORS_ALLOWED_ORIGINS is unnecessary in-cluster** (unset).
- **Single shared Secret callout:** all three workloads (API, hook Job, reaper)
  mount the same Secret template. This structurally eliminates the
  per-service-copy drift bug class fixed in PR #42 (reaper crashed because its
  DJANGO_SECRET_KEY was configured separately from the API's). The ADR and
  primer both say so.

### 3. Frontend workload

- New `frontend/Dockerfile`: stage 1 `node:20` runs `npm ci && npm run build`
  with **no `VITE_API_BASE`** — `apiBase.ts` then defaults to relative
  `/api/v1`, which is exactly right behind the shared Ingress. Stage 2
  `nginx:alpine` serves `dist/` with `frontend/nginx.conf`
  (`try_files $uri /index.html` SPA fallback).
- Deployment (1 replica — static files), Service, probes on `GET /`.
- **Ingress** (class nginx): `/api` → api Service, `/` → web Service, one host
  → one origin at `http://localhost/`; no CORS, no baked URLs.

### 4. Migration hook Job (ADR-0007)

- Annotations: `helm.sh/hook: pre-install,pre-upgrade`, `hook-weight: "0"`,
  `hook-delete-policy: before-hook-creation` (prior Job cleaned before re-run;
  **failed Jobs remain** for debugging). `backoffLimit: 1`,
  `activeDeadlineSeconds: 300`.
- Command: a small sh loop — wait for DB readiness via Django's own config
  (`manage.py check --database default` retried with timeout; no URL parsing),
  then `manage.py migrate`, then `manage.py seed_demo --refresh` **iff
  `seed.refreshOnDeploy`** (true in kind values, matching Render's behavior
  today; false in values-prod.yaml).
- **Rollback stance:** Helm hooks do not run on `helm rollback`; no
  down-migrations exist. Rollback reverts code only; schema stays ahead. Safe
  **because** of the expand-contract discipline adopted in ADR-0006 from
  migration #1 — the seam laid before Kubernetes existed here is what makes the
  Kubernetes rollback safe. ADR-0007 records this plus the rejected
  alternatives (init container: runs N× per rollout, races, blocks scale-up;
  pipeline-driven Job: splits the deploy so `helm install` alone no longer
  yields a working app — named as the possible Milestone-4 evolution).

### 5. Reaper CronJob

Same backend image, `manage.py reap_ephemeral`, schedule from values (default
`"17 4 * * *"`), `concurrencyPolicy: Forbid`, history limits 1 success /
3 failures. Consumes the shared Secret (§2).

### 6. Dev database (values-gated)

`postgres.enabled` (default **true** for kind): single-replica StatefulSet of
`postgis/postgis:16-3.4` with a 1Gi PVC and Service; credentials in the shared
Secret; `DATABASE_URL` defaults to the in-cluster DNS form
(`postgis://…@annotated-maps-postgres:5432/annotated_maps`). In
values-prod.yaml: `postgres.enabled: false` and `DATABASE_URL` must be supplied
at install time (`--set` / external secret) — never committed.

### 7. Local workflow

- `deploy/kind/cluster.yaml`: one-node cluster with `extraPortMappings`
  80/443 → host, so the Ingress serves plain `http://localhost/`.
- **Makefile targets:**
  - `make kind-up` — create cluster from config; install ingress-nginx (kind
    provider manifest) and metrics-server (patched `--kubelet-insecure-tls`,
    required for HPA on kind); wait for both ready.
  - `make deploy` — build api + web images (`:dev` tags), `kind load
    docker-image` both, `helm upgrade --install annotated-maps
    deploy/helm/annotated-maps -n annotated-maps --create-namespace --wait`.
  - `make kind-down` — delete the cluster.
  - `make helm-checks` — the static suite (lint + unittest + kubeconform),
    same commands CI runs.
- Local images use `imagePullPolicy: Never` in kind values — the
  `IfNotPresent`-silently-pulls-from-registry footgun is documented in the
  primer's troubleshooting table.

### 8. CI

Two jobs added to `ci.yml`:

- **`helm` (static):** `helm lint` both values files; helm-unittest template
  tests (hook annotations present; all three workloads consume the shared
  Secret; probes point at `/api/v1/health`; HPA/PDB render; postgres templates
  absent when `postgres.enabled=false`); `kubeconform` schema-validates
  `helm template` output for both values files.
- **`helm-install` (live):** `helm/kind-action` cluster; build + `kind load`
  both images; `helm install --wait --timeout 5m`; `kubectl rollout status`
  on both Deployments; `helm test` (chart test pod curls
  `/api/v1/health` in-cluster); port-forwarded curl of the web Service for the
  static tier. ~3–4 min; a public green "installs on Kubernetes" check.

### 9. Kubernetes primer (`docs/kubernetes-primer.md`)

A newcomer-oriented document for a developer with Docker familiarity and no
Kubernetes/Helm background. Audience-tested content — it formalizes the
explanation that unblocked this design review. Outline:

1. **Mental model:** image → container → Kubernetes (declarations, the
   reconcile loop) → Helm (templates + values → release; upgrade/rollback),
   each anchored to this repo's Render equivalents.
2. **Objects in this repo:** a table mapping every chart template to what it
   declares, its Render/compose equivalent, and the file path
   (`deploy/helm/annotated-maps/templates/…`).
3. **Cookbook — start/stop and daily commands:** cluster lifecycle
   (`make kind-up/deploy/kind-down`); seeing what's running (`kubectl get
   pods/deploy/svc -n annotated-maps`, `describe`, `logs`, `logs -f`,
   `exec -it … -- sh`, `port-forward`); Helm lifecycle (`helm status`,
   `history`, `upgrade`, `rollback`, `test`); inspecting a migration hook run;
   triggering the reaper manually (`kubectl create job --from=cronjob/…`).
4. **Troubleshooting table:** image not found (forgot `kind load` /
   pullPolicy), hook Job failed (how to read its logs before it's cleaned),
   DB not ready, HPA `<unknown>` targets (metrics-server), port 80 already in
   use on the host.
5. **Where to go deeper:** kind/Helm/K8s official docs, plus ADR-0007 and this
   spec.

### 10. Docs & tracking

README gets a "Run it on Kubernetes" section linking the primer. When the
slice ships: ROADMAP.md Milestone 1 row flips to ✅ with proof links (chart
path, green `helm-install` run, ADR); the board card moves In Progress → Done
on merge (In Progress from spec time).

## Risks & mitigations

- **CI flakiness of the live job:** kind-in-CI is well-trodden
  (`helm/kind-action`); `--wait --timeout 5m` + explicit rollout status keep
  failures crisp. If it flakes in practice, the job can gain one retry —
  decision deferred until observed.
- **Host port 80 conflicts** for local users: documented in the primer;
  cluster.yaml can be edited to map 8080 instead.
- **Drift between chart and render.yaml:** both descriptions of the same app
  coexist until Milestone 3 retires Render. The spec accepts this; the chart
  is the forward-looking artifact and CI keeps it honest.
- **Seed refresh on every `make deploy`:** matches Render's per-deploy
  behavior and is values-gated; developers who want to keep local edits set
  `seed.refreshOnDeploy=false` (documented in the primer).

## Testing summary

helm-unittest template tests + kubeconform (static, CI + `make helm-checks`);
live kind install + `helm test` + smoke curls (CI); manual: `make kind-up &&
make deploy`, click through the app (tour included) at `http://localhost/`.
Backend/frontend suites unaffected (no app-code changes expected beyond the new
frontend Dockerfile/nginx.conf, which the live CI job exercises).
