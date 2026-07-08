# ADR-0007: Database migrations run as Helm pre-upgrade hook Jobs
- Status: accepted
- Date: 2026-07-08
## Context

On Render, `predeploy.sh` (migrate + seed refresh) runs before new code takes
traffic. Kubernetes has no built-in pre-deploy phase, so the ordering must be
rebuilt somewhere: in Helm's lifecycle, in the pods themselves, or in a
pipeline.

## Decision

A Job runs `manage.py migrate` (plus the values-gated demo-seed refresh) as a
Helm hook. Its `helm.sh/hook` annotation is values-gated on
`postgres.enabled`, because "before Helm rolls any Deployment" means
different things depending on where the database lives:

- **`postgres.enabled=true` (dev, in-cluster PostGIS)**: `post-install,pre-upgrade`.
  On a fresh install the database is itself a normal chart resource created
  by this same release, so it does not exist yet when pre-install hooks run.
  Migrate must therefore run **after** install (once the StatefulSet is up)
  but still **before** every upgrade, so upgrades keep the migrate-before-code
  guarantee.
- **`postgres.enabled=false` (prod, external database)**: `pre-install,pre-upgrade`.
  The database pre-exists independently of the release, so the strict
  Render-equivalent ordering — migrate before any code, including the very
  first install — holds with no caveat.

Both phases keep `pre-upgrade`, so upgrades on both dev and prod always
migrate before new code rolls. `hook-delete-policy: before-hook-creation`
keeps failed Jobs around for debugging. All workloads (API, this hook, the
reaper) consume one shared Secret, so their DB/security config cannot drift
apart (the config-drift bug class we hit on Render in PR #42).

## Consequences

- Deploys are strictly ordered: migrate → roll pods, on both prod (always)
  and dev upgrades. On a **fresh dev install only**, code pods start
  concurrently with (or before) the migrate Job, since it is deferred to
  post-install. This is benign: the API's readiness/liveness probes are
  DB-free (see the health endpoint), and there is no data yet for unmigrated
  code to corrupt — the pods simply serve traffic against an empty,
  about-to-be-migrated schema until the hook completes.
- A stuck migration fails the release visibly (`activeDeadlineSeconds`).
- Schema rollforward-only; code rollback stays safe under expand-contract.
- Helm hooks do not run on `helm rollback`, and down-migrations don't exist
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
