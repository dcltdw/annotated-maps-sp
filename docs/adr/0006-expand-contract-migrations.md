<!-- doc-status: dated -->

# ADR-0006: Expand-contract (backward-compatible) migrations
- Status: accepted
- Date: 2026-06-09
## Context
Once production data exists, destructive or blocking migrations cause downtime and risk data loss.
## Decision
Every schema change follows expand-contract: add new (nullable / with default) → backfill → switch reads/writes → contract (drop old) in a later release. No column drop or type change in the same deploy that begins using it.
## Consequences
Zero-downtime deploys are possible from day one; migrations stay reversible and safe under load.
