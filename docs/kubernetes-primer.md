<!-- doc-status: living -->

# Kubernetes & Helm primer (this repo)

## 1. The mental model

You already know the first step: `docker build` turns source into an image, a
content-addressed, runnable artifact. `docker run` turns that image into a
container — a process with its own filesystem and network namespace. Nothing
about Kubernetes changes this part. This repo still builds `annotated-maps-api`
and `annotated-maps-web` as ordinary Docker images (`backend/Dockerfile`,
`frontend/Dockerfile`); Kubernetes only takes over *after* the image exists.

Where `docker run` starts one container on one machine and stops caring,
Kubernetes asks you to *declare* what you want running and then keeps making
it true. You write YAML saying "2 replicas of the API, each with these env
vars, probed on `/api/v1/health`" — a `Deployment` — and a controller loop
inside the cluster continuously compares that declaration against reality: is
a pod missing? Start one. Did a probe start failing? Stop routing to it. This
is the reconcile loop, and it's the single biggest conceptual shift from
Docker: you stop running commands and start writing desired state. A `Service`
is the same idea applied to networking — a stable in-cluster address that
follows pods around as they're replaced. An `Ingress` is a Service for
external traffic, routing by host/path to the right Service. A `CronJob` is
what it sounds like: a `Job` (a pod that runs to completion) on a schedule.
None of this is new capability over `docker-compose` — it's the same
container primitives, but declared once and continuously enforced instead of
started and forgotten.

Helm is the packaging layer on top of these declarations. Writing ten
near-identical YAML files by hand for dev and prod is exactly the kind of
duplication you'd refactor out of application code, so Helm gives you
**templates** (the YAML with `{{ .Values.x }}` placeholders — everything under
`deploy/helm/annotated-maps/templates/`) plus **values** (the environment-specific
numbers: replica counts, image tags, whether the in-cluster database is even
turned on). `helm install` renders the templates against a values file and
hands the result to Kubernetes as one unit, called a **release**; `helm
upgrade` re-renders and applies the diff; `helm rollback` reverts to a
previous release's rendered manifests. Crucially, Helm also has **hooks** —
resources tagged to run at specific points in a release's lifecycle
(`pre-install`, `post-install`, `pre-upgrade`) rather than as part of the
normal rollout — which is how this chart reproduces a step Kubernetes has no
native concept of.

That step is worth naming directly, because it's the one piece of this stack
that isn't generic Kubernetes knowledge but a decision specific to this repo.
On Render, `render.yaml`'s `preDeployCommand` runs `backend/predeploy.sh`
(migrate, then refresh the demo seed) *before* new code takes traffic — Render
has a first-class predeploy phase. Kubernetes doesn't, so this chart rebuilds
that ordering with a hook `Job` (`migrate-hook-job.yaml`) instead of an init
container, so migrations run once per release rather than once per pod. Same
idea as the reaper: `render.yaml`'s cron service becomes a native `CronJob`
here, no code changes, no Kubernetes-specific carve-out — it's the same
`manage.py reap_ephemeral` command Render already runs nightly.

`kind` is the last piece: a real Kubernetes cluster, API server and all,
running as Docker containers on your laptop. It is not a simulation or a
subset — the chart that installs cleanly on kind is the same chart, unchanged,
that later targets a managed cluster like EKS. That's the payoff of learning
this stack against a free local cluster now: there is no second migration to
do later.

## 2. What runs where (objects in this repo)

| Object (file) | What it declares | Render/compose equivalent |
|---|---|---|
| Deployment ([api-deployment.yaml](../deploy/helm/annotated-maps/templates/api-deployment.yaml)) | 2 API pods, probed on /api/v1/health, replaced gradually on upgrade | the annotated-maps-api service |
| Service ([api-service.yaml](../deploy/helm/annotated-maps/templates/api-service.yaml)) | stable in-cluster address for the API pods | Render internal routing |
| Deployment ([web-deployment.yaml](../deploy/helm/annotated-maps/templates/web-deployment.yaml)) | nginx serving the built SPA | the annotated-maps-web static site |
| Ingress ([ingress.yaml](../deploy/helm/annotated-maps/templates/ingress.yaml)) | one host: /api→API, /→SPA (same-origin, no CORS) | per-service Render URLs |
| Job ([migrate-hook-job.yaml](../deploy/helm/annotated-maps/templates/migrate-hook-job.yaml)) | migrate (+seed) BEFORE each deploy — Helm hook | predeploy.sh |
| CronJob ([reaper-cronjob.yaml](../deploy/helm/annotated-maps/templates/reaper-cronjob.yaml)) | nightly reap at 17 4 * * * | the annotated-maps-reaper cron |
| StatefulSet ([postgres-statefulset.yaml](../deploy/helm/annotated-maps/templates/postgres-statefulset.yaml)) | dev-only PostGIS + volume (off in prod values) | docker-compose db |
| Secret ([secret.yaml](../deploy/helm/annotated-maps/templates/secret.yaml)) | ONE shared secret for api+hook+reaper (prevents drift — see ADR-0007) | per-service env vars |
| HPA ([hpa.yaml](../deploy/helm/annotated-maps/templates/hpa.yaml)) | 2→4 API pods on CPU | (no Render equivalent) |
| PDB ([pdb.yaml](../deploy/helm/annotated-maps/templates/pdb.yaml)) | never below 1 API pod during maintenance | (no Render equivalent) |

A note on the migrate Job's hook phase, since it's easy to misread as a plain
`pre-upgrade` hook: it's values-gated (see [ADR-0007](adr/0007-migrations-via-helm-hooks.md)).
With the in-cluster dev database (`postgres.enabled=true`), the DB is itself
created by this same release, so migrate can't run pre-install — nothing
would exist to connect to — and instead runs `post-install,pre-upgrade`. With
an external prod database (`postgres.enabled=false`), the DB already exists
independently of the release, so migrate stays strict `pre-install,pre-upgrade`,
matching Render's ordering exactly. Both cases keep `pre-upgrade`, so every
upgrade — dev or prod — always migrates before new code rolls.

## 3. Cookbook — start, stop, look around

Everything below assumes you're in the repo root; the Make targets wrap the
exact commands CI runs.

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
| Local seed edits vanish on deploy | seed.refreshOnDeploy=true (matches Render, not the chart's prod values) | `helm upgrade ... --set seed.refreshOnDeploy=false` |

## 5. Going deeper

- [kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/)
- Helm docs: [charts](https://helm.sh/docs/topics/charts/), [hooks](https://helm.sh/docs/topics/charts_hooks/)
- Kubernetes concepts: [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/), [Job](https://kubernetes.io/docs/concepts/workloads/controllers/job/), [CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/), [Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/), [HorizontalPodAutoscaler](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- This repo: [ADR-0007 — migrations via Helm hooks](adr/0007-migrations-via-helm-hooks.md) and the [Milestone 1 design spec](superpowers/specs/2026-07-08-helm-kind-milestone-design.md)
