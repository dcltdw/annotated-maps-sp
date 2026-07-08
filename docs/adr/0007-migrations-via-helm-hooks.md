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
