# Milestone 1 — Helm Chart + kind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Helm chart that brings up the entire app (API, frontend, dev PostGIS, migration hook, reaper) on a local kind cluster via `make kind-up && make deploy`, verified statically and live in CI, with ADR-0007 and a newcomer primer.

**Architecture:** One chart at `deploy/helm/annotated-maps/` with a single shared Secret consumed by every workload; migrations run as a `pre-install,pre-upgrade` hook Job; the dev database is values-gated; the frontend is a new nginx image behind a shared Ingress (same-origin, so the SPA's relative `/api/v1` default just works).

**Tech Stack:** Helm 3, kind, helm-unittest (plugin), kubeconform, ingress-nginx, metrics-server, nginx:alpine, GitHub Actions (`helm/kind-action`).

**Spec:** `docs/superpowers/specs/2026-07-08-helm-kind-milestone-design.md` — read it before starting any task.

## Global Constraints

- Chart name/release/namespace: `annotated-maps`. Resource names: `annotated-maps-api`, `-web`, `-postgres`, `-migrate`, `-reaper`, `-secrets`, `-test-connection`.
- Local images: `annotated-maps-api:dev` and `annotated-maps-web:dev`, `imagePullPolicy: Never` in default values (kind), loaded via `kind load docker-image`.
- API port 8000 (image ENV `PORT=8000`); web port 80. Health path: `/api/v1/health` (DB-free — do NOT add a DB check to it). Probes MUST send header `Host: localhost` (Django `ALLOWED_HOSTS` rejects pod-IP Hosts otherwise).
- Values keys are the contract across tasks — see Task 1's `values.yaml` and use those exact paths everywhere.
- All static checks must pass before every commit: `make helm-checks` (helm lint × 2 values files, helm unittest, kubeconform × 2). Until Task 5 creates the Makefile, run the underlying commands directly (given per task).
- Prod-shaped lint/template always passes `--set secrets.databaseUrl=postgis://placeholder:pw@example.com:5432/placeholder` (the chart `fail`s without a DB URL when `postgres.enabled=false` — intended).
- Tool prerequisites (local): `docker`, `kind`, `helm`, `kubectl`, `kubeconform`. If any is missing, STOP and report BLOCKED with the install command (`brew install kind helm kubectl kubeconform`) — do not install software on the machine unprompted.
- Existing app code is untouched except: new `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`. No backend changes at all.
- Repo conventions: commits carry the `Co-Authored-By` model trailer; PR bodies use `## Summary / ## Provenance / ## Reasoning / ## Testing / ## Risk & rollback`.

## File Structure

```
deploy/helm/annotated-maps/{Chart.yaml, values.yaml, values-prod.yaml,
  templates/{_helpers.tpl, secret.yaml, api-deployment.yaml, api-service.yaml,
    web-deployment.yaml, web-service.yaml, ingress.yaml, migrate-hook-job.yaml,
    reaper-cronjob.yaml, hpa.yaml, pdb.yaml, postgres-statefulset.yaml,
    postgres-service.yaml, tests/test-connection.yaml},
  tests/{api_test.yaml, hook_test.yaml, workloads_test.yaml, postgres_test.yaml}}
deploy/kind/cluster.yaml
frontend/{Dockerfile, nginx.conf, .dockerignore}
Makefile
docs/adr/0007-migrations-via-helm-hooks.md
docs/kubernetes-primer.md
.github/workflows/ci.yml            (+2 jobs)
README.md, ROADMAP.md               (sections updated in Task 7)
```

---

### Task 1: Chart skeleton — Secret, API workload, static test harness

**Files:**
- Create: `deploy/helm/annotated-maps/Chart.yaml`
- Create: `deploy/helm/annotated-maps/values.yaml`
- Create: `deploy/helm/annotated-maps/templates/_helpers.tpl`
- Create: `deploy/helm/annotated-maps/templates/secret.yaml`
- Create: `deploy/helm/annotated-maps/templates/api-deployment.yaml`
- Create: `deploy/helm/annotated-maps/templates/api-service.yaml`
- Test: `deploy/helm/annotated-maps/tests/api_test.yaml`

**Interfaces:**
- Produces (later tasks rely on these exact names): helpers `annotated-maps.fullname`, `annotated-maps.labels`, `annotated-maps.selectorLabels`, `annotated-maps.databaseUrl`; Secret `{fullname}-secrets`; values paths `image.api.*`, `image.web.*`, `api.*`, `web.*`, `ingress.*`, `hpa.*`, `pdb.*`, `postgres.*`, `secrets.*`, `seed.refreshOnDeploy`, `reaper.schedule`.

- [ ] **Step 1: Install the helm-unittest plugin (idempotent)**

Run: `helm plugin list | grep -q unittest || helm plugin install https://github.com/helm-unittest/helm-unittest`
Expected: plugin listed.

- [ ] **Step 2: Write the failing template test**

```yaml
# deploy/helm/annotated-maps/tests/api_test.yaml
suite: api deployment
templates:
  - templates/api-deployment.yaml
tests:
  - it: probes hit the DB-free health endpoint with an explicit Host header
    asserts:
      - equal:
          path: spec.template.spec.containers[0].livenessProbe.httpGet.path
          value: /api/v1/health
      - equal:
          path: spec.template.spec.containers[0].readinessProbe.httpGet.path
          value: /api/v1/health
      - contains:
          path: spec.template.spec.containers[0].livenessProbe.httpGet.httpHeaders
          content: { name: Host, value: localhost }
  - it: consumes the shared secret via envFrom
    asserts:
      - contains:
          path: spec.template.spec.containers[0].envFrom
          content: { secretRef: { name: RELEASE-NAME-annotated-maps-secrets } }
  - it: defaults to 2 replicas with resource requests set (HPA prerequisite)
    asserts:
      - equal: { path: spec.replicas, value: 2 }
      - equal:
          path: spec.template.spec.containers[0].resources.requests.cpu
          value: 100m
```

- [ ] **Step 3: Run to verify it fails**

Run: `helm unittest deploy/helm/annotated-maps`
Expected: FAIL (template file missing / chart invalid).

- [ ] **Step 4: Write Chart.yaml and values.yaml**

```yaml
# deploy/helm/annotated-maps/Chart.yaml
apiVersion: v2
name: annotated-maps
description: Annotated Maps — Django/PostGIS API + Vite SPA, packaged for Kubernetes.
type: application
version: 0.1.0
appVersion: "0.1.0"
```

```yaml
# deploy/helm/annotated-maps/values.yaml
# Defaults target the LOCAL kind cluster. Prod-shaped overrides: values-prod.yaml.
image:
  api:
    repository: annotated-maps-api
    tag: dev
    pullPolicy: Never   # kind: image is `kind load`ed; Never prevents silent registry pulls
  web:
    repository: annotated-maps-web
    tag: dev
    pullPolicy: Never

api:
  replicas: 2
  resources:
    requests: { cpu: 100m, memory: 256Mi }
    limits: { cpu: 500m, memory: 512Mi }
  env:
    sandboxMode: "true"
    djangoDebug: "false"
    allowedHosts: "localhost"
    secureSslRedirect: "false"

web:
  replicas: 1

ingress:
  className: nginx
  host: localhost

hpa:
  enabled: true
  minReplicas: 2
  maxReplicas: 4
  targetCPUUtilizationPercentage: 70

pdb:
  enabled: true
  minAvailable: 1

postgres:
  enabled: true                     # dev-only in-cluster PostGIS; prod uses external DATABASE_URL
  image: postgis/postgis:16-3.4
  storage: 1Gi
  database: annotated_maps
  user: annotated_maps
  password: localdev                # dev-only credential, mirrors docker-compose

secrets:
  djangoSecretKey: local-insecure-dev-key   # dev-only; prod supplies real values at install
  modToken: ""
  databaseUrl: ""                   # empty → derived from postgres.* when enabled; REQUIRED when postgres disabled

seed:
  refreshOnDeploy: true             # matches Render's per-deploy seed refresh; false in prod values

reaper:
  schedule: "17 4 * * *"
```

- [ ] **Step 5: Write _helpers.tpl**

```yaml
{{/* deploy/helm/annotated-maps/templates/_helpers.tpl */}}
{{- define "annotated-maps.name" -}}
{{- .Chart.Name -}}
{{- end }}

{{- define "annotated-maps.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{- define "annotated-maps.labels" -}}
app.kubernetes.io/name: {{ include "annotated-maps.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{- define "annotated-maps.selectorLabels" -}}
app.kubernetes.io/name: {{ include "annotated-maps.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* DATABASE_URL: explicit value wins; else derived from the in-cluster postgres;
     else the chart refuses to render — a prod install without a DB URL is a mistake. */}}
{{- define "annotated-maps.databaseUrl" -}}
{{- if .Values.secrets.databaseUrl -}}
{{- .Values.secrets.databaseUrl -}}
{{- else if .Values.postgres.enabled -}}
{{- printf "postgis://%s:%s@%s-postgres:5432/%s" .Values.postgres.user .Values.postgres.password (include "annotated-maps.fullname" .) .Values.postgres.database -}}
{{- else -}}
{{- fail "secrets.databaseUrl is required when postgres.enabled=false" -}}
{{- end -}}
{{- end }}
```

- [ ] **Step 6: Write secret.yaml, api-deployment.yaml, api-service.yaml**

```yaml
# deploy/helm/annotated-maps/templates/secret.yaml
# THE one Secret every workload consumes (api, migrate hook, reaper, postgres password).
# One source of truth prevents per-workload config drift (the PR #42 bug class).
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "annotated-maps.fullname" . }}-secrets
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
type: Opaque
stringData:
  DJANGO_SECRET_KEY: {{ .Values.secrets.djangoSecretKey | quote }}
  DATABASE_URL: {{ include "annotated-maps.databaseUrl" . | quote }}
  MOD_TOKEN: {{ .Values.secrets.modToken | quote }}
  POSTGRES_PASSWORD: {{ .Values.postgres.password | quote }}
```

```yaml
# deploy/helm/annotated-maps/templates/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "annotated-maps.fullname" . }}-api
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    app.kubernetes.io/component: api
spec:
  replicas: {{ .Values.api.replicas }}
  selector:
    matchLabels:
      {{- include "annotated-maps.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: api
  template:
    metadata:
      labels:
        {{- include "annotated-maps.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: api
    spec:
      containers:
        - name: api
          image: "{{ .Values.image.api.repository }}:{{ .Values.image.api.tag }}"
          imagePullPolicy: {{ .Values.image.api.pullPolicy }}
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: {{ include "annotated-maps.fullname" . }}-secrets
          env:
            - name: SANDBOX_MODE
              value: {{ .Values.api.env.sandboxMode | quote }}
            - name: DJANGO_DEBUG
              value: {{ .Values.api.env.djangoDebug | quote }}
            - name: DJANGO_ALLOWED_HOSTS
              value: {{ .Values.api.env.allowedHosts | quote }}
            - name: SECURE_SSL_REDIRECT
              value: {{ .Values.api.env.secureSslRedirect | quote }}
          livenessProbe:
            httpGet:
              path: /api/v1/health
              port: 8000
              httpHeaders:
                - name: Host
                  value: {{ .Values.ingress.host }}
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /api/v1/health
              port: 8000
              httpHeaders:
                - name: Host
                  value: {{ .Values.ingress.host }}
            initialDelaySeconds: 5
            periodSeconds: 5
          resources:
            {{- toYaml .Values.api.resources | nindent 12 }}
```

```yaml
# deploy/helm/annotated-maps/templates/api-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "annotated-maps.fullname" . }}-api
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    app.kubernetes.io/component: api
spec:
  selector:
    {{- include "annotated-maps.selectorLabels" . | nindent 4 }}
    app.kubernetes.io/component: api
  ports:
    - port: 8000
      targetPort: 8000
```

- [ ] **Step 7: Run tests + lint to green**

Run: `helm unittest deploy/helm/annotated-maps && helm lint deploy/helm/annotated-maps`
Expected: unittest suites PASS; lint `0 chart(s) failed`.

- [ ] **Step 8: kubeconform the rendered output**

Run: `helm template annotated-maps deploy/helm/annotated-maps | kubeconform -strict -summary -kubernetes-version 1.30.0`
Expected: 0 invalid. (If kubeconform is missing locally, STOP → BLOCKED per Global Constraints.)

- [ ] **Step 9: Commit**

```bash
git add deploy/helm
git commit -m "feat(helm): chart skeleton — shared Secret + API workload + template tests"
```

---

### Task 2: Dev PostGIS + migration hook Job + ADR-0007

**Files:**
- Create: `deploy/helm/annotated-maps/templates/postgres-statefulset.yaml`
- Create: `deploy/helm/annotated-maps/templates/postgres-service.yaml`
- Create: `deploy/helm/annotated-maps/templates/migrate-hook-job.yaml`
- Create: `docs/adr/0007-migrations-via-helm-hooks.md`
- Test: `deploy/helm/annotated-maps/tests/hook_test.yaml`, `deploy/helm/annotated-maps/tests/postgres_test.yaml`

**Interfaces:**
- Consumes: helpers + Secret + values from Task 1.
- Produces: Service DNS name `{fullname}-postgres` (the databaseUrl helper already points at it); hook Job `{fullname}-migrate`.

- [ ] **Step 1: Write the failing tests**

```yaml
# deploy/helm/annotated-maps/tests/hook_test.yaml
suite: migration hook job
templates:
  - templates/migrate-hook-job.yaml
tests:
  - it: is a pre-install,pre-upgrade hook that keeps failed jobs for debugging
    asserts:
      - equal:
          path: metadata.annotations["helm.sh/hook"]
          value: pre-install,pre-upgrade
      - equal:
          path: metadata.annotations["helm.sh/hook-delete-policy"]
          value: before-hook-creation
      - equal: { path: spec.backoffLimit, value: 1 }
  - it: consumes the shared secret and refreshes the seed by default
    asserts:
      - contains:
          path: spec.template.spec.containers[0].envFrom
          content: { secretRef: { name: RELEASE-NAME-annotated-maps-secrets } }
      - matchRegex:
          path: spec.template.spec.containers[0].args[0]
          pattern: seed_demo --refresh
  - it: omits the seed refresh when disabled (prod shape)
    set: { seed: { refreshOnDeploy: false } }
    asserts:
      - notMatchRegex:
          path: spec.template.spec.containers[0].args[0]
          pattern: seed_demo
```

```yaml
# deploy/helm/annotated-maps/tests/postgres_test.yaml
suite: dev postgres gating
templates:
  - templates/postgres-statefulset.yaml
  - templates/postgres-service.yaml
tests:
  - it: renders the dev database by default (kind values)
    asserts:
      - hasDocuments: { count: 1 }
  - it: renders nothing when disabled (prod shape)
    set: { postgres: { enabled: false }, secrets: { databaseUrl: "postgis://u:p@h:5432/d" } }
    asserts:
      - hasDocuments: { count: 0 }
```

Run: `helm unittest deploy/helm/annotated-maps` → Expected: new suites FAIL (templates missing).

- [ ] **Step 2: Write the postgres templates**

```yaml
# deploy/helm/annotated-maps/templates/postgres-statefulset.yaml
{{- if .Values.postgres.enabled }}
# Dev-only in-cluster PostGIS. Prod disables this and supplies secrets.databaseUrl.
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ include "annotated-maps.fullname" . }}-postgres
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    app.kubernetes.io/component: postgres
spec:
  serviceName: {{ include "annotated-maps.fullname" . }}-postgres
  replicas: 1
  selector:
    matchLabels:
      {{- include "annotated-maps.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: postgres
  template:
    metadata:
      labels:
        {{- include "annotated-maps.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: postgres
    spec:
      containers:
        - name: postgres
          image: {{ .Values.postgres.image }}
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_DB
              value: {{ .Values.postgres.database | quote }}
            - name: POSTGRES_USER
              value: {{ .Values.postgres.user | quote }}
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: {{ include "annotated-maps.fullname" . }}-secrets
                  key: POSTGRES_PASSWORD
          readinessProbe:
            exec:
              command: ["pg_isready", "-U", {{ .Values.postgres.user | quote }}]
            initialDelaySeconds: 5
            periodSeconds: 5
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: {{ .Values.postgres.storage }}
{{- end }}
```

```yaml
# deploy/helm/annotated-maps/templates/postgres-service.yaml
{{- if .Values.postgres.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "annotated-maps.fullname" . }}-postgres
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    app.kubernetes.io/component: postgres
spec:
  selector:
    {{- include "annotated-maps.selectorLabels" . | nindent 4 }}
    app.kubernetes.io/component: postgres
  ports:
    - port: 5432
      targetPort: 5432
{{- end }}
```

- [ ] **Step 3: Write the hook Job**

```yaml
# deploy/helm/annotated-maps/templates/migrate-hook-job.yaml
# Runs BEFORE Helm touches the Deployments (Render's preDeployCommand, translated).
# Rollback stance: hooks don't run on `helm rollback`; schema stays ahead of code,
# which is safe under the expand-contract discipline (ADR-0006). See ADR-0007.
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "annotated-maps.fullname" . }}-migrate
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    app.kubernetes.io/component: migrate
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "0"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 300
  template:
    metadata:
      labels:
        {{- include "annotated-maps.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: migrate
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: "{{ .Values.image.api.repository }}:{{ .Values.image.api.tag }}"
          imagePullPolicy: {{ .Values.image.api.pullPolicy }}
          envFrom:
            - secretRef:
                name: {{ include "annotated-maps.fullname" . }}-secrets
          env:
            - name: SANDBOX_MODE
              value: {{ .Values.api.env.sandboxMode | quote }}
            - name: DJANGO_DEBUG
              value: {{ .Values.api.env.djangoDebug | quote }}
            - name: DJANGO_ALLOWED_HOSTS
              value: {{ .Values.api.env.allowedHosts | quote }}
            - name: SECURE_SSL_REDIRECT
              value: {{ .Values.api.env.secureSslRedirect | quote }}
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -e
              i=0
              # Wait for the DB using Django's own connection config (no URL parsing).
              until uv run python manage.py shell -c "import django.db; django.db.connections['default'].ensure_connection()" >/dev/null 2>&1; do
                i=$((i+1))
                if [ "$i" -ge 30 ]; then echo "database never became ready" >&2; exit 1; fi
                echo "waiting for database ($i/30)"; sleep 2
              done
              uv run python manage.py migrate --noinput
              {{- if .Values.seed.refreshOnDeploy }}
              uv run python manage.py seed_demo --refresh
              {{- end }}
```

(Deviation from the spec's sketch, with reason: the spec suggested `manage.py check --database default` for the wait; `ensure_connection()` is used instead because `check` does not reliably open a connection on all backends, and the point is to prove connectivity. Same spirit — Django's own config, no URL parsing.)

- [ ] **Step 4: Write ADR-0007**

```markdown
# 7. Database migrations run as Helm pre-upgrade hook Jobs

Date: 2026-07-08

## Status

Accepted

## Context

On Render, `predeploy.sh` (migrate + seed refresh) runs before new code takes
traffic. Kubernetes has no built-in pre-deploy phase, so the ordering must be
rebuilt somewhere: in Helm's lifecycle, in the pods themselves, or in a
pipeline.

## Decision

A Job annotated `helm.sh/hook: pre-install,pre-upgrade` runs
`manage.py migrate` (plus the values-gated demo-seed refresh) to completion
before Helm rolls any Deployment. One run per deploy regardless of replica
count; a failed migration aborts the upgrade before new code serves traffic.
`hook-delete-policy: before-hook-creation` keeps failed Jobs around for
debugging. All workloads (API, this hook, the reaper) consume one shared
Secret, so their DB/security config cannot drift apart (the config-drift bug
class we hit on Render in PR #42).

## Rollback

Helm hooks do not run on `helm rollback`, and down-migrations don't exist
here. Rollback therefore reverts code only; the schema stays at the newer
version. That is safe **because of ADR-0006**: every migration is
expand-contract (backward-compatible), so old code runs correctly against a
newer schema. The rollback safety comes from a discipline adopted at
migration #1 — before Kubernetes was in the picture — not from Helm
mechanics.

## Alternatives considered

- **Init container running migrate on every API pod** — runs N× per rollout
  and again on every restart: concurrent migrations race, a slow migration
  blocks HPA scale-ups and crash-loop recovery, and a seed refresh there
  would rebuild demo data on every pod start. Right only for single-replica
  setups.
- **Pipeline-driven migration Job (no hook)** — explicit CD-step ordering,
  common in mature setups, but `helm install` alone would no longer produce
  a working app, violating this milestone's success criterion. Milestone 4's
  pipeline may revisit.

## Consequences

- Deploys are strictly ordered: migrate → roll pods.
- A stuck migration fails the release visibly (`activeDeadlineSeconds`).
- Schema rollforward-only; code rollback stays safe under expand-contract.
```

- [ ] **Step 5: Run all static checks to green**

Run: `helm unittest deploy/helm/annotated-maps && helm lint deploy/helm/annotated-maps && helm template annotated-maps deploy/helm/annotated-maps | kubeconform -strict -summary -kubernetes-version 1.30.0`
Expected: all suites PASS, lint clean, 0 invalid.

- [ ] **Step 6: Commit**

```bash
git add deploy/helm docs/adr/0007-migrations-via-helm-hooks.md
git commit -m "feat(helm): dev PostGIS + migration pre-upgrade hook Job (ADR-0007)"
```

---

### Task 3: Frontend image + web workload + Ingress

**Files:**
- Create: `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`
- Create: `deploy/helm/annotated-maps/templates/web-deployment.yaml`
- Create: `deploy/helm/annotated-maps/templates/web-service.yaml`
- Create: `deploy/helm/annotated-maps/templates/ingress.yaml`
- Test: extend `deploy/helm/annotated-maps/tests/workloads_test.yaml` (create it)

**Interfaces:**
- Consumes: helpers/values from Task 1.
- Produces: image `annotated-maps-web:dev`; Service `{fullname}-web:80`; Ingress routing `/api`→api:8000, `/`→web:80 on host `.Values.ingress.host`.

- [ ] **Step 1: Write the failing template test**

```yaml
# deploy/helm/annotated-maps/tests/workloads_test.yaml
suite: web + ingress
templates:
  - templates/web-deployment.yaml
  - templates/ingress.yaml
tests:
  - it: web probes /
    template: templates/web-deployment.yaml
    asserts:
      - equal:
          path: spec.template.spec.containers[0].readinessProbe.httpGet.path
          value: /
  - it: ingress routes /api to the api service and / to the web service
    template: templates/ingress.yaml
    asserts:
      - equal:
          path: spec.rules[0].http.paths[0].path
          value: /api
      - equal:
          path: spec.rules[0].http.paths[0].backend.service.name
          value: RELEASE-NAME-annotated-maps-api
      - equal:
          path: spec.rules[0].http.paths[1].path
          value: /
      - equal:
          path: spec.rules[0].http.paths[1].backend.service.name
          value: RELEASE-NAME-annotated-maps-web
```

Run: `helm unittest deploy/helm/annotated-maps` → FAIL (templates missing).

- [ ] **Step 2: Write the frontend image files**

```dockerfile
# frontend/Dockerfile
# Stage 1: build the SPA. No VITE_API_BASE on purpose — apiBase.ts then defaults to
# the relative "/api/v1", which is correct behind the chart's same-origin Ingress.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: serve the static build.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
```

```nginx
# frontend/nginx.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback: unknown paths render the app shell (client-side routing).
    location / {
        try_files $uri /index.html;
    }
}
```

```
# frontend/.dockerignore
node_modules
dist
playwright-report
test-results
```

- [ ] **Step 3: Build the image to prove the Dockerfile works**

Run: `docker build -f frontend/Dockerfile -t annotated-maps-web:dev frontend`
Expected: image builds; `docker run --rm -d -p 8082:80 annotated-maps-web:dev` + `curl -fsS http://localhost:8082/ | head -c 100` shows the SPA's HTML; stop the container.

- [ ] **Step 4: Write web-deployment, web-service, ingress templates**

```yaml
# deploy/helm/annotated-maps/templates/web-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "annotated-maps.fullname" . }}-web
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    app.kubernetes.io/component: web
spec:
  replicas: {{ .Values.web.replicas }}
  selector:
    matchLabels:
      {{- include "annotated-maps.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: web
  template:
    metadata:
      labels:
        {{- include "annotated-maps.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: web
    spec:
      containers:
        - name: web
          image: "{{ .Values.image.web.repository }}:{{ .Values.image.web.tag }}"
          imagePullPolicy: {{ .Values.image.web.pullPolicy }}
          ports:
            - containerPort: 80
          livenessProbe:
            httpGet: { path: /, port: 80 }
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet: { path: /, port: 80 }
            initialDelaySeconds: 2
            periodSeconds: 5
```

```yaml
# deploy/helm/annotated-maps/templates/web-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "annotated-maps.fullname" . }}-web
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    app.kubernetes.io/component: web
spec:
  selector:
    {{- include "annotated-maps.selectorLabels" . | nindent 4 }}
    app.kubernetes.io/component: web
  ports:
    - port: 80
      targetPort: 80
```

```yaml
# deploy/helm/annotated-maps/templates/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "annotated-maps.fullname" . }}
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
spec:
  ingressClassName: {{ .Values.ingress.className }}
  rules:
    - host: {{ .Values.ingress.host }}
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: {{ include "annotated-maps.fullname" . }}-api
                port: { number: 8000 }
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "annotated-maps.fullname" . }}-web
                port: { number: 80 }
```

- [ ] **Step 5: Static checks to green** (same three commands as Task 2 Step 5). Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf frontend/.dockerignore deploy/helm
git commit -m "feat(helm): nginx frontend image + web workload + same-origin Ingress"
```

---

### Task 4: Reaper CronJob, HPA, PDB, helm-test pod, values-prod.yaml

**Files:**
- Create: `deploy/helm/annotated-maps/templates/reaper-cronjob.yaml`
- Create: `deploy/helm/annotated-maps/templates/hpa.yaml`
- Create: `deploy/helm/annotated-maps/templates/pdb.yaml`
- Create: `deploy/helm/annotated-maps/templates/tests/test-connection.yaml`
- Create: `deploy/helm/annotated-maps/values-prod.yaml`
- Test: `deploy/helm/annotated-maps/tests/operations_test.yaml` (new file)

**Interfaces:**
- Consumes: helpers/Secret/values from Tasks 1–3.

- [ ] **Step 1: Write the failing tests**

```yaml
# deploy/helm/annotated-maps/tests/operations_test.yaml
suite: reaper + hpa + pdb
templates:
  - templates/reaper-cronjob.yaml
  - templates/hpa.yaml
  - templates/pdb.yaml
tests:
  - it: reaper runs the reap command on the values schedule and shares the secret
    template: templates/reaper-cronjob.yaml
    asserts:
      - equal: { path: spec.schedule, value: "17 4 * * *" }
      - equal: { path: spec.concurrencyPolicy, value: Forbid }
      - contains:
          path: spec.jobTemplate.spec.template.spec.containers[0].envFrom
          content: { secretRef: { name: RELEASE-NAME-annotated-maps-secrets } }
  - it: hpa targets the api deployment between 2 and 4 replicas
    template: templates/hpa.yaml
    asserts:
      - equal: { path: spec.scaleTargetRef.name, value: RELEASE-NAME-annotated-maps-api }
      - equal: { path: spec.minReplicas, value: 2 }
      - equal: { path: spec.maxReplicas, value: 4 }
  - it: pdb keeps at least one api pod
    template: templates/pdb.yaml
    asserts:
      - equal: { path: spec.minAvailable, value: 1 }
```

Run `helm unittest deploy/helm/annotated-maps` → FAIL (templates missing).

- [ ] **Step 2: Write the templates**

```yaml
# deploy/helm/annotated-maps/templates/reaper-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {{ include "annotated-maps.fullname" . }}-reaper
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    app.kubernetes.io/component: reaper
spec:
  schedule: {{ .Values.reaper.schedule | quote }}
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 1
      template:
        metadata:
          labels:
            {{- include "annotated-maps.selectorLabels" . | nindent 12 }}
            app.kubernetes.io/component: reaper
        spec:
          restartPolicy: Never
          containers:
            - name: reaper
              image: "{{ .Values.image.api.repository }}:{{ .Values.image.api.tag }}"
              imagePullPolicy: {{ .Values.image.api.pullPolicy }}
              envFrom:
                - secretRef:
                    name: {{ include "annotated-maps.fullname" . }}-secrets
              env:
                - name: SANDBOX_MODE
                  value: {{ .Values.api.env.sandboxMode | quote }}
                - name: DJANGO_DEBUG
                  value: {{ .Values.api.env.djangoDebug | quote }}
                - name: DJANGO_ALLOWED_HOSTS
                  value: {{ .Values.api.env.allowedHosts | quote }}
                - name: SECURE_SSL_REDIRECT
                  value: {{ .Values.api.env.secureSslRedirect | quote }}
              command: ["uv", "run", "python", "manage.py", "reap_ephemeral"]
```

```yaml
# deploy/helm/annotated-maps/templates/hpa.yaml
{{- if .Values.hpa.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "annotated-maps.fullname" . }}-api
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "annotated-maps.fullname" . }}-api
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.hpa.targetCPUUtilizationPercentage }}
{{- end }}
```

```yaml
# deploy/helm/annotated-maps/templates/pdb.yaml
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "annotated-maps.fullname" . }}-api
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable }}
  selector:
    matchLabels:
      {{- include "annotated-maps.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: api
{{- end }}
```

```yaml
# deploy/helm/annotated-maps/templates/tests/test-connection.yaml
# `helm test annotated-maps` runs this pod: proves the API answers in-cluster.
apiVersion: v1
kind: Pod
metadata:
  name: {{ include "annotated-maps.fullname" . }}-test-connection
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
  annotations:
    "helm.sh/hook": test
spec:
  restartPolicy: Never
  containers:
    - name: health-check
      image: curlimages/curl:8.10.1
      command:
        - sh
        - -c
        - >-
          curl -fsS -H "Host: {{ .Values.ingress.host }}"
          http://{{ include "annotated-maps.fullname" . }}-api:8000/api/v1/health
```

- [ ] **Step 3: Write values-prod.yaml**

```yaml
# deploy/helm/annotated-maps/values-prod.yaml
# ILLUSTRATIVE prod shape — not a working config. Registry refs land in
# Milestone 4; secrets are always supplied at install time, never committed.
image:
  api:
    repository: ghcr.io/dcltdw/annotated-maps-api   # placeholder registry ref
    tag: "set-by-pipeline"
    pullPolicy: IfNotPresent
  web:
    repository: ghcr.io/dcltdw/annotated-maps-web
    tag: "set-by-pipeline"
    pullPolicy: IfNotPresent

api:
  env:
    sandboxMode: "true"          # the public demo IS the sandbox
    djangoDebug: "false"
    allowedHosts: "annotated-maps.example.com"
    secureSslRedirect: "true"

ingress:
  host: annotated-maps.example.com

postgres:
  enabled: false                 # prod uses an external (Neon) database

secrets:
  djangoSecretKey: ""            # REQUIRED at install: --set secrets.djangoSecretKey=...
  databaseUrl: ""                # REQUIRED at install: --set secrets.databaseUrl=...
  modToken: ""

seed:
  refreshOnDeploy: false
```

- [ ] **Step 4: Static checks to green, both values files**

```bash
helm unittest deploy/helm/annotated-maps
helm lint deploy/helm/annotated-maps
helm lint deploy/helm/annotated-maps -f deploy/helm/annotated-maps/values-prod.yaml \
  --set secrets.databaseUrl=postgis://placeholder:pw@example.com:5432/placeholder
helm template annotated-maps deploy/helm/annotated-maps | kubeconform -strict -summary -kubernetes-version 1.30.0
helm template annotated-maps deploy/helm/annotated-maps -f deploy/helm/annotated-maps/values-prod.yaml \
  --set secrets.databaseUrl=postgis://placeholder:pw@example.com:5432/placeholder | kubeconform -strict -summary -kubernetes-version 1.30.0
```
Expected: all green. (The `--set` is intended: prod values without a DB URL must FAIL to render — verify that too: running the template command WITHOUT the `--set` must print the `fail` message.)

- [ ] **Step 5: Commit**

```bash
git add deploy/helm
git commit -m "feat(helm): reaper CronJob, HPA, PDB, helm-test pod, prod-shaped values"
```

---

### Task 5: kind config + Makefile

**Files:**
- Create: `deploy/kind/cluster.yaml`
- Create: `Makefile` (repo root — check none exists first; if one exists, STOP → BLOCKED)

**Interfaces:**
- Produces: `make kind-up`, `make deploy`, `make kind-down`, `make helm-checks` — the exact commands CI (Task 6) and the primer (Task 7) reference.

- [ ] **Step 1: Verify tools** — `command -v docker kind helm kubectl kubeconform` (see Global Constraints; BLOCKED if missing).

- [ ] **Step 2: Write the kind cluster config**

```yaml
# deploy/kind/cluster.yaml
# One-node local cluster. Host ports 80/443 map into the node so the
# ingress-nginx controller (installed by `make kind-up`) serves http://localhost/.
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
```

- [ ] **Step 3: Write the Makefile**

```makefile
# Makefile — local Kubernetes parity workflow (see docs/kubernetes-primer.md)
CLUSTER := annotated-maps
NS := annotated-maps
CHART := deploy/helm/annotated-maps
INGRESS_NGINX_VERSION := controller-v1.11.2
METRICS_SERVER_VERSION := v0.7.2
PROD_PLACEHOLDER_DB := postgis://placeholder:pw@example.com:5432/placeholder

.PHONY: kind-up deploy kind-down helm-checks

kind-up: ## Create the local cluster + ingress-nginx + metrics-server
	kind create cluster --name $(CLUSTER) --config deploy/kind/cluster.yaml
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/$(INGRESS_NGINX_VERSION)/deploy/static/provider/kind/deploy.yaml
	kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/$(METRICS_SERVER_VERSION)/components.yaml
	kubectl -n kube-system patch deployment metrics-server --type=json \
		-p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
	kubectl -n ingress-nginx wait --for=condition=Available deployment/ingress-nginx-controller --timeout=180s

deploy: ## Build images, load into kind, install/upgrade the release
	docker build -f backend/Dockerfile -t annotated-maps-api:dev .
	docker build -f frontend/Dockerfile -t annotated-maps-web:dev frontend
	kind load docker-image annotated-maps-api:dev --name $(CLUSTER)
	kind load docker-image annotated-maps-web:dev --name $(CLUSTER)
	helm upgrade --install annotated-maps $(CHART) -n $(NS) --create-namespace --wait --timeout 5m

kind-down: ## Delete the local cluster (removes everything)
	kind delete cluster --name $(CLUSTER)

helm-checks: ## Static chart verification — same commands CI runs
	helm lint $(CHART)
	helm lint $(CHART) -f $(CHART)/values-prod.yaml --set secrets.databaseUrl=$(PROD_PLACEHOLDER_DB)
	helm plugin list | grep -q unittest || helm plugin install https://github.com/helm-unittest/helm-unittest
	helm unittest $(CHART)
	helm template annotated-maps $(CHART) | kubeconform -strict -summary -kubernetes-version 1.30.0
	helm template annotated-maps $(CHART) -f $(CHART)/values-prod.yaml --set secrets.databaseUrl=$(PROD_PLACEHOLDER_DB) | kubeconform -strict -summary -kubernetes-version 1.30.0
```

Note: `kubectl … wait` for ingress-nginx can race the Deployment's creation; if it errors with "not found", retry once after `sleep 5` (acceptable to add a small `sleep 5;` before the wait line if observed).

- [ ] **Step 4: Verify `make helm-checks` green.** Expected: full static suite passes via make.

- [ ] **Step 5: Live local verification (the milestone's core loop)**

```bash
make kind-up          # ~1-2 min
make deploy           # builds, loads, installs; --wait blocks until healthy
kubectl -n annotated-maps get pods   # expect: 2 api Running, 1 web, 1 postgres, migrate Completed
helm test annotated-maps -n annotated-maps --logs   # health-check pod PASSES
curl -fsS http://localhost/api/v1/health            # {"status": ...}
curl -fsS http://localhost/ | head -c 200           # SPA HTML
```
Expected: all green. If port 80 is occupied on the host, note it and use the primer's troubleshooting entry (edit cluster.yaml hostPort). Leave the cluster up for Task 8.

- [ ] **Step 6: Commit**

```bash
git add deploy/kind/cluster.yaml Makefile
git commit -m "feat: kind cluster config + Makefile parity workflow"
```

---

### Task 6: CI — static + live jobs

**Files:**
- Modify: `.github/workflows/ci.yml` (append two jobs after the existing ones; touch nothing else)

**Interfaces:**
- Consumes: `make helm-checks` (Task 5), both Dockerfiles, the chart.

- [ ] **Step 1: Append the two jobs**

```yaml
  helm:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-helm@v4
      - name: Install kubeconform
        run: |
          curl -sSL https://github.com/yannh/kubeconform/releases/download/v0.6.7/kubeconform-linux-amd64.tar.gz | tar xz
          sudo mv kubeconform /usr/local/bin/
      - run: make helm-checks

  helm-install:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Create kind cluster
        uses: helm/kind-action@v1
        with:
          cluster_name: chart-testing
      - name: Build images
        run: |
          docker build -f backend/Dockerfile -t annotated-maps-api:dev .
          docker build -f frontend/Dockerfile -t annotated-maps-web:dev frontend
      - name: Load images into kind
        run: |
          kind load docker-image annotated-maps-api:dev --name chart-testing
          kind load docker-image annotated-maps-web:dev --name chart-testing
      - name: Install the chart
        run: helm install annotated-maps deploy/helm/annotated-maps -n annotated-maps --create-namespace --wait --timeout 5m
      - name: Rollout status
        run: |
          kubectl -n annotated-maps rollout status deploy/annotated-maps-api --timeout 120s
          kubectl -n annotated-maps rollout status deploy/annotated-maps-web --timeout 120s
      - name: helm test (in-cluster health check)
        run: helm test annotated-maps -n annotated-maps --logs
      - name: Smoke the web tier
        run: |
          kubectl -n annotated-maps port-forward svc/annotated-maps-web 8081:80 &
          sleep 3
          curl -fsS http://localhost:8081/ | grep -qi "<!doctype html"
```

(No ingress controller in the CI cluster on purpose — the Ingress object installs fine without one; in-cluster reachability is proven by `helm test` + port-forward. The full ingress path is exercised locally in Tasks 5/8.)

- [ ] **Step 2: Validate the workflow file** — `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` → parses.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: helm static checks + live kind install jobs"
```

(The jobs run when the PR opens — treat a red `helm`/`helm-install` job on the PR as a failed task and fix before proceeding to review.)

---

### Task 7: Kubernetes primer + README + ROADMAP flip

**Files:**
- Create: `docs/kubernetes-primer.md`
- Modify: `README.md` (add a "Run it on Kubernetes" section after "Local development")
- Modify: `ROADMAP.md` (Milestone 1 table row → ✅ with proof links; status section)

**Interfaces:** consumes the Make targets and file paths exactly as shipped in Tasks 1–6.

- [ ] **Step 1: Write the primer.** Structure and all tables/commands below are exact requirements; connective prose is authored at execution — audience is a developer comfortable with Docker but new to Kubernetes/Helm; register matches the repo's docs (plain, concrete, no hype). Required outline:

```markdown
# Kubernetes & Helm primer (this repo)

## 1. The mental model
[Prose: image → container → Kubernetes (declarations + reconcile loop) → Helm
(templates + values → release; upgrade/rollback). Anchor every concept to this
repo's Render equivalents (render.yaml, predeploy.sh, the reaper cron). ~500
words. End with: kind = a real cluster in Docker on your laptop; the same chart
later targets EKS unchanged.]

## 2. What runs where (objects in this repo)
| Object (file) | What it declares | Render/compose equivalent |
|---|---|---|
| Deployment ([api-deployment.yaml](../deploy/helm/annotated-maps/templates/api-deployment.yaml)) | 2 API pods, probed on /api/v1/health, replaced gradually on upgrade | the annotated-maps-api service |
| Service ([api-service.yaml](...)) | stable in-cluster address for the API pods | Render internal routing |
| Deployment ([web-deployment.yaml](...)) | nginx serving the built SPA | the annotated-maps-web static site |
| Ingress ([ingress.yaml](...)) | one host: /api→API, /→SPA (same-origin, no CORS) | per-service Render URLs |
| Job ([migrate-hook-job.yaml](...)) | migrate (+seed) BEFORE each deploy — Helm hook | predeploy.sh |
| CronJob ([reaper-cronjob.yaml](...)) | nightly reap at 17 4 * * * | the annotated-maps-reaper cron |
| StatefulSet ([postgres-statefulset.yaml](...)) | dev-only PostGIS + volume (off in prod values) | docker-compose db |
| Secret ([secret.yaml](...)) | ONE shared secret for api+hook+reaper (prevents drift — see ADR-0007) | per-service env vars |
| HPA ([hpa.yaml](...)) | 2→4 API pods on CPU | (no Render equivalent) |
| PDB ([pdb.yaml](...)) | never below 1 API pod during maintenance | (no Render equivalent) |

## 3. Cookbook — start, stop, look around
### Cluster lifecycle
    make kind-up      # create cluster + ingress + metrics-server (~2 min)
    make deploy       # build images, load, helm install/upgrade — app at http://localhost/
    make kind-down    # delete everything
### Seeing what's running
    kubectl -n annotated-maps get pods            # list; STATUS/READY/RESTARTS
    kubectl -n annotated-maps get deploy,svc,ingress,hpa
    kubectl -n annotated-maps describe pod <name> # events: why isn't it starting?
    kubectl -n annotated-maps logs deploy/annotated-maps-api          # api logs
    kubectl -n annotated-maps logs -f deploy/annotated-maps-api       # follow
    kubectl -n annotated-maps exec -it deploy/annotated-maps-api -- sh  # shell in a pod
    kubectl -n annotated-maps port-forward svc/annotated-maps-api 8000:8000  # bypass ingress
### Helm lifecycle
    helm -n annotated-maps status annotated-maps    # release state
    helm -n annotated-maps history annotated-maps   # revisions
    helm -n annotated-maps rollback annotated-maps  # previous revision (code only — see ADR-0007)
    helm test annotated-maps -n annotated-maps --logs  # in-cluster health check
    make helm-checks                                  # static lint/tests, same as CI
### The migration hook & the reaper
    kubectl -n annotated-maps logs job/annotated-maps-migrate   # last deploy's migration run
    kubectl -n annotated-maps create job --from=cronjob/annotated-maps-reaper reaper-manual
    kubectl -n annotated-maps logs job/reaper-manual

## 4. Troubleshooting
| Symptom | Cause | Fix |
|---|---|---|
| Pod `ErrImageNeverPull` | image not loaded into kind | `make deploy` (runs `kind load`); pullPolicy Never is deliberate |
| Install hangs then fails at hook | migration Job failed | `kubectl -n annotated-maps logs job/annotated-maps-migrate` (failed Jobs are kept) |
| API pods 400 on probes | ALLOWED_HOSTS vs probe Host header | probes send Host: localhost by design; check api.env.allowedHosts |
| `helm test` fails | API not actually healthy | `kubectl describe` the test pod + api pods |
| HPA shows `<unknown>` targets | metrics-server missing/unpatched | `make kind-up` installs+patches it; `kubectl top pods` to verify |
| Port 80 busy on host | something else on :80 | edit deploy/kind/cluster.yaml hostPort (e.g. 8080), recreate cluster |
| Local seed edits vanish on deploy | seed.refreshOnDeploy=true (matches prod) | `helm upgrade ... --set seed.refreshOnDeploy=false` |

## 5. Going deeper
[Links: kind quick start, Helm docs (charts/hooks), K8s concepts (Deployment,
Job, CronJob, Ingress, HPA); plus this repo's ADR-0007 and the milestone spec.]
```

- [ ] **Step 2: README section** — after the "Local development" section add:

```markdown
## Run it on Kubernetes

The app ships as a Helm chart (`deploy/helm/annotated-maps`) that runs end-to-end
on a local [kind](https://kind.sigs.k8s.io/) cluster:

```bash
make kind-up    # one-time cluster (ingress + metrics-server included)
make deploy     # build, load, install — app at http://localhost/
```

New to Kubernetes? Start with the [Kubernetes primer](docs/kubernetes-primer.md).
Design rationale: [ADR-0007](docs/adr/0007-migrations-via-helm-hooks.md) and the
[milestone spec](docs/superpowers/specs/2026-07-08-helm-kind-milestone-design.md).
```

- [ ] **Step 3: ROADMAP flip** — in `ROADMAP.md`: Milestone 1 table row status `📋 Planned` → `✅ Shipped`, Proof cell → `[chart](deploy/helm/annotated-maps/) · [ADR-0007](docs/adr/0007-migrations-via-helm-hooks.md) · [primer](docs/kubernetes-primer.md) · [CI runs](https://github.com/dcltdw/annotated-maps-sp/actions)`; in the Milestone 1 section change "**Done means:**" line to past tense noting it shipped. Do not touch other rows.

- [ ] **Step 4: Commit**

```bash
git add docs/kubernetes-primer.md README.md ROADMAP.md
git commit -m "docs: Kubernetes primer, README K8s section, roadmap Milestone 1 shipped"
```

---

### Task 8: End-to-end verification (controller-level)

**Files:** none — verification only.

- [ ] **Step 1:** `make helm-checks` + full backend/frontend suites still green (nothing app-side changed, confirm anyway).
- [ ] **Step 2:** Fresh loop from nothing: `make kind-down || true`, then `make kind-up && make deploy`. Verify pod set (2 api / 1 web / 1 postgres / migrate Completed), `helm test` passes, `curl http://localhost/api/v1/health` and `curl http://localhost/` both good.
- [ ] **Step 3:** Headless-Playwright screenshot of `http://localhost/` (the seeded map should render; the tour auto-starts on a fresh profile) — Read the PNG to confirm the app genuinely works through the Ingress.
- [ ] **Step 4:** Rollback drill: `helm upgrade` with a trivial change (`--set web.replicas=2`), then `helm rollback`, confirm `helm test` still passes — demonstrates the ADR-0007 story end to end.
- [ ] **Step 5:** HPA sanity: `kubectl -n annotated-maps get hpa` shows real utilization (not `<unknown>`).
- [ ] **Step 6:** Leave the cluster running for the user; branch ready for PR (repo's five rigor sections; move the board card; note in the PR that `helm-install` CI is the public proof).
