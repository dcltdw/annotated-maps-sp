# ADR-0005: Tenant isolation via RLS, enforced when auth lands
- Status: accepted
- Date: 2026-06-09
## Context
Multi-tenant data needs hard isolation, but Slice A uses a single seeded tenant and trivial auth.
## Decision
Thread `tenant_id` on every domain row from day one; enable Postgres Row-Level Security policies when real auth lands.
## Consequences
The column and access paths exist now; turning on RLS later hardens a rule that is already threaded rather than adding a column under fire.
