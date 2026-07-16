# Production Lenses & Architectural Concerns

- **Date:** 2026-06-09
- **Status:** Historical snapshot — the day-one production-concern triage (2026-06-09), preserved as written and **not** updated as milestones ship. For current status, see [ROADMAP.md](../../ROADMAP.md).
- **Purpose:** Capture, from day one, the big-picture lenses a production version of Annotated Maps must address — so cross-cutting concerns are *designed-for (seamed)* rather than bolted on later. Most are **out of scope for Slice A**; the **Foundation-now** items are baked into Slice A's groundwork.

> **Note (2026-07-16).** This is a snapshot of the original day-one triage, kept as a record of what was foreseen and *seamed* before any code shipped — not a live tracker. Several 🟡 *"seam now, build later"* items have since been built: observability (Milestone 2), liveness/readiness probes and SLOs (Milestones 1–2), and dependency scanning + SBOM (Milestone 4). The 🟡 markers below are deliberately left as the original decision; the point of the artifact is that these were seamed *here first* and built later. Current milestone status lives in [ROADMAP.md](../../ROADMAP.md).

## Triage legend

- 🟢 **Foundation now** — cheap structural choice, painful to retrofit; built into Slice A groundwork.
- 🟡 **Seam now, build later** — design the hook now, defer the work to its own slice.
- ⚪ **Note & revisit** — no architectural commitment needed yet.

## Headline: scale out, not up

A **stateless app tier** behind a load balancer + **per-tenant database scaling**. Vertical scaling is only ever a stopgap. `tenant_id` on every row is the partition seam.

## Lenses

### 1. Scalability & performance
- 🟢 Stateless app tier (no local state → scale out); DB connection pooling (serverless Postgres needs it).
- 🟢 **PostGIS** for geometry + spatial queries; geometry stored as **GeoJSON/WKB**. Already implied by Slice A's regions + point-in-region.
- 🟡 Read replicas; **partition/shard by tenant** (`tenant_id` is the seam); app cache (Redis) — kept viable by keeping the visibility engine **pure/deterministic** so results are cacheable; CDN for tiles/assets (planned: Cloudflare R2 — never built; see the design spec).
- 🟡 Background-job scaling (Postgres queue → dedicated broker) behind the existing job interface.

### 2. Security & privacy
- 🟢 RLS tenant isolation (column threaded; policies later); **authZ as one centralized policy layer + an always-green authorization test suite**; secrets management, TLS, encryption-at-rest, security headers (CSP/HSTS).
- 🟢 **Audit-log seam** (security + content-change events) written through one helper from early.
- 🟡 STRIDE threat model; supply-chain (SAST, dependency + secret scanning, SBOM, signed commits); abuse/rate-limiting (generalized from the demo limits); trust & safety / moderation.
- ⚪ Vulnerability-disclosure policy, bug bounty.

### 3. Reliability & availability
- 🟢 **Backups + tested restore** the moment there's production data (document RPO/RTO); **idempotent writes + optimistic concurrency** (version field — also the offline-sync seam).
- 🟡 Timeouts/retries/graceful degradation, circuit breakers, liveness/readiness checks; SLOs.
- ⚪ Multi-AZ / failover / redundancy (cost; statelessness keeps the door open).

### 4. Observability & operability
- 🟢 **Tenant/user/correlation IDs threaded through structured logs** from line one; error tracking + health endpoint; **expand-contract migration discipline from migration #1**.
- 🟡 Metrics, distributed tracing, alerting, dashboards, runbooks, on-call.

### 5. Data governance & compliance
- 🟢 **GDPR/CCPA-able data model** — every datum attributable to a user/tenant and **deletable + exportable**; a soft-vs-hard-delete + purge path (generalize the 7-day demo wipe).
- 🟢 **OSM/ODbL tile attribution & licensing** — legally required the instant we render OSM tiles (Slice A demo).
- 🟡 Retention policies, PII minimization, data residency (tenant attribute seam), uploaded-map copyright/DMCA.

### 6. Internationalization & accessibility
- 🟢 **i18n structure** — UTF-8, externalized strings, UTC storage, locale-agnostic data. Ship English-only, but *structured*.
- 🟢 **a11y rule: never encode meaning in color alone** — visibility types carry icon **+** label, not just hue; keyboard-operable map controls; WCAG targets.

### 7. Interoperability & extensibility
- 🟢 **API versioning from `/v1`**; **GeoJSON/WKB** geometry → natural import/export (pairs with PostGIS, ties to GDPR export); the **preset + pluggable rule-types/collection-kinds/map-sources** system as the extensibility seam.
- 🟡 Public API / webhooks / SSO / embeds; **full-text search** over notes/places (Postgres FTS is the cheap seam).
- 🟡 **GeoJSON import review** — sandboxed validation of third-party files (size/vertex limits, content sanitization), description-vs-content verification (geographic containment, geometry-kind checks), and visual approval overlaid on existing data (duplicate detection, accept/reject). Building blocks shipped by the richer-seed slice: Pydantic seed schema, geometry lint, escaping `seed_preview` renderer (spec `2026-07-04-richer-seed-data-design.md`).

### 8. Mobile, offline & sync
- 🟡 PWA → native (API-first ✓).
- ⚪ True offline editing + conflict resolution (CRDT/OT) is a large later effort — modeling notes/sections as independently-syncable units + optimistic concurrency is the seam toward it.

### 9. Business, product & legal
- 🟡 Monetization/billing/plans/usage-limits (per-tenant settings/feature-flags is the seam); org/team management + invitations; notifications ("someone appended to your note"); ToS/privacy policy; content moderation / abuse reporting.
- ⚪ Real-time collaboration (websockets); COPPA/age considerations.

## Foundation-now seams (built into Slice A groundwork)

| # | Seam | What we do now | Why retrofit is costly |
|---|---|---|---|
| 1 | **PostGIS + GeoJSON/WKB** | Enable PostGIS; store all geometry as PostGIS types; point-in-region via spatial query | Migrating geometry storage + rewriting spatial logic on live data |
| 2 | **Stateless app tier + pooling** | No local session/file state; sessions in DB, files in object storage; connection pooling | Re-architecting state out of processes after scaling pain |
| 3 | **API versioning `/v1`** | All endpoints under `/api/v1` | Breaking existing clients to introduce versioning |
| 4 | **Observability context** | Logs carry request + tenant + user IDs from the first handler | Threading context through every log call after the fact |
| 5 | **Expand-contract migrations** | Every migration backward-compatible (add → backfill → switch → drop) from #1 | Can't get zero-downtime once destructive migrations are habit |
| 6 | **GDPR-able delete/export** | User/tenant data identifiable + removable; purge mechanism + export path | Untangling un-attributed data and orphaned rows later |
| 7 | **Idempotency + optimistic concurrency** | Version field on mutable entities; idempotency keys on writes | Adding concurrency control after lost-update bugs surface on live data |
| 8 | **i18n structure + a11y** | UTF-8, externalized strings, UTC; meaning never by color alone; keyboard controls | Extracting strings across a finished UI; redoing a color-only design |
| 9 | **OSM attribution/licensing** | Render required OSM/ODbL attribution; comply with tile-provider ToS | It's a legal/compliance gap, not just a tech change |
| 10 | **Audit-log seam** | Append-only event log via one helper from early | You can't reconstruct history you never recorded |

## How deferred lenses get built

Each 🟡/⚪ item becomes its own spec → plan → slice (or ADR) when prioritized. This document is the standing **backlog of architectural concerns** — reviewed as the product grows.
