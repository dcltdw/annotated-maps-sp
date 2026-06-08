# Annotated Maps — Design Spec

- **Date:** 2026-06-08
- **Status:** Draft for review
- **Scope of this document:** the full production target as the north star, and the detailed design of **Slice A** (the first buildable slice).

---

## 1. Purpose & goals

Annotated Maps lets a curator place richly-permissioned notes on a map — a real-world slippy map or a static image/PDF — and control, per note and per *section within a note*, exactly who can see what.

Two goals drive the project:

1. **Portfolio piece.** A publicly hosted, polished, production-shaped app that demonstrates senior+ engineering breadth (security, multi-tenancy, API design, testing rigor, operable infrastructure, disciplined process).
2. **Personally useful.** Ultimately a GM's tool for D&D campaign maps. The public demo, however, is a **real-world Boston map with real notes** (favorite restaurants, running routes), because that is instantly legible to employers.

The product is **domain-neutral**: D&D and "places I love around Boston" are two *presets* over one engine, not two apps.

## 2. Product concept & presets

- **Maps** hold **notes**. A note may be anchored to a **point**, a drawn **region/boundary**, the **whole map**, or **nothing** (free-floating "plot notes").
- A note is composed of **sections**, each with its own **visibility rule**. This is the core differentiator: one note can be partly public, partly restricted, partly secret.
- **Contributors** (e.g. players, or other users) add their own notes and may **append** to a curator's note — visually distinct, governed by its own visibility, never mutating the original.
- **Presets:**
  - **Boston (public demo):** real slippy map; visibility leans on Public / Audience / Private, plus one reputation-gated example.
  - **D&D (private, later):** static/PDF maps; the attribute-gate appears as "Arcana ≥ X"; "GM/Player" are the curator/contributor roles.

## 3. Architecture decisions (summary)

| Area | Decision |
|---|---|
| Backend | **Django + Django Ninja** (typed endpoints + automatic OpenAPI), Django ORM + migrations, Django auth primitives as the "vetted libs" base |
| Frontend | **React + TypeScript SPA, installable PWA**, built with Vite; **MapLibre GL** for both slippy maps and static-image overlays |
| API | **API-first**, versioned, OpenAPI contract with a generated typed client shared by web (and future native) |
| Database | **PostgreSQL**, with **Row-Level Security** as the tenant-isolation enforcement (switched on with auth; column threaded from day one) |
| Async | **Postgres-backed task queue (Procrastinate)** — no Redis, no extra cost; behind an `EmailSender`/job interface |
| Object storage | **S3-compatible (Cloudflare R2)** for map files, served via short-lived **signed URLs**; behind a storage interface (local in dev) |
| Auth strategy | **Self-implemented on vetted libraries** (deferred behind a seam in Slice A) |
| Clients | Web/mobile via responsive PWA now; **native app deferred**, enabled by the API-first boundary |

**Hosting target (~$7/mo):** always-on small app instance (Render/Railway/Fly) · Neon free Postgres · Cloudflare R2 free tier · static PWA on Cloudflare Pages · Resend/SES free email. Tunable; final platform pinned in an ADR.

## 4. Decomposition & roadmap

The project is **decomposed into slices**, each its own spec → plan → build cycle. Slice A is large but coherent; its **implementation plan is internally phased** with review checkpoints.

**Slice A — Core annotated-maps product (this spec).** Internal phases:

- **A1** — Map + point notes + the visibility engine (4 rule types, section-level, teasers) + the view-switcher seam.
- **A2** — Regions/boundaries (drawing + region-anchored notes + spatial selection helper).
- **A3** — Labels + authorization-aware bulk operations.
- **A4** — Note revisions/history + soft delete + optimistic concurrency.
- **A5** — Editable public demo hardening (abuse limits, nightly reset) + deploy + CI/CD + preview envs.

**Deferred slices (production target, each with a Slice-A seam):**

- **Identity & access** — registration, email verification, password login, password reset, **pluggable** 2FA (email OTP first; TOTP/WebAuthn later), brute-force protection, RBAC via per-tenant memberships.
- **Multi-tenancy hardening** — RLS policies enabled, tenant resolution (subdomain/path), cross-tenant IDOR audit.
- **Reputation earning** — upvotes/scoring that *produce* the reputation attribute the gate already consumes.
- **D&D preset** — static/PDF maps, image-pixel coordinates, "Arcana ≥ X" gate UI, campaign ergonomics.
- **Native mobile client** — thin client over the existing API.
- **Admin** — platform/tenant administration (Django admin as a head start), per-tenant settings/feature-flags (generalizing admin-configurable 2FA).
- **Operational depth** — backups/DR + runbook, distributed tracing, SLOs, PII export/deletion.

## 5. Domain model

Neutral vocabulary (D&D/real-world terms are presentation-layer labels over these):

- **Tenant (Game/Space)** — the multi-tenancy boundary. Every domain row carries `tenant_id` from day one.
- **User** — an identity. In Slice A, users are seeded; the *current* user is chosen by the view-switcher (auth seam). Carries attributes including **`reputation`** (seeded in Slice A).
- **Membership** — `(user, tenant, role)`. Roles: **Owner/Curator**, **Contributor**, **Viewer**. (A user may hold different roles in different tenants.)
- **Group** — a named audience within a tenant (e.g. "Running club"); has members.
- **Map** — belongs to a tenant; a slippy map (geographic CRS) or a static image/PDF (image-pixel CRS, later). References a map file in object storage.
- **Note** — belongs to a map; carries `author_id`; anchored to a **point**, a **region**, the **whole map**, or **nothing**. Soft-deletable; revisioned.
- **Section** — an ordered part of a note; holds content and **one VisibilityRule**; teaser flag (default off → invisible).
- **Append** — a first-class note attached to a parent note (its own author, visibility, sections); never mutates the parent.
- **Region/Boundary** — a drawn geometry on a map; may anchor notes; may act as a **spatial selector** for bulk operations.
- **Label** — a tenant-scoped tag applied to notes; the grouping primitive for **bulk operations**.
- **Revision** — an immutable prior state of a note/section, with author + timestamp.

## 6. The visibility engine

A pure domain service: `canView(viewer, section) → { visible | teaser | hidden }`, evaluated per section. It is **content authorization**, kept deliberately separate from **access authentication**, and routed through a single **centralized policy layer** (no scattered role checks).

**Four visibility rule types:**

| Rule | Visible when… | Real-world | D&D |
|---|---|---|---|
| **Public** | always | everyone | everyone |
| **Audience** | viewer is a listed user or a member of a listed group | "Friends", "Running club" | a party/faction |
| **Attribute gate** | a viewer attribute meets a threshold | **reputation ≥ N**, age ≥ 21, verified | **Arcana ≥ X** |
| **Private** | viewer is the owner | owner only | GM only |

**Teaser behavior:** restricted sections are **fully invisible by default**. A section may opt into a **teaser** — a redacted placeholder revealing that hidden content exists. Configurable per section.

**Viewer-resolution seam:** all access flows through one "resolve current tenant + current viewer (role, group memberships, attributes)" function — hardcoded to the view-switcher in Slice A, backed by real sessions later. The view-switcher is retained forever as a QA/demo tool for the engine.

**Testing:** the engine is a pure function of `viewer × section`, making it the ideal target for **property-based tests** (e.g. "a Private section is never visible to a non-owner under any generated viewer").

## 7. Slice A scope

**In scope (built):** real Boston slippy map; point + region notes + whole-map + free-floating notes; sections with all four visibility rules; per-section teaser; contributor notes + appends (visually distinct); labels + authorization-aware bulk ops; spatial selection within a region; note revisions/history + soft delete + optimistic concurrency; view-switcher (Owner / Contributor / Viewer-with-reputation); editable public demo with abuse limits; OpenAPI + typed client; CI/CD; per-PR preview environments.

**Seamed (stubbed, architected-for):**

| Deferred capability | Slice A seam |
|---|---|
| Real auth/sessions | `current viewer` resolved by view-switcher behind one function |
| Multi-tenancy isolation | `tenant_id` on every row; single seeded tenant; RLS policies added later |
| Email (verification/OTP/reset) | all sends go through an `EmailSender` interface (console/no-op in A) |
| Object storage | storage interface (local in dev → R2 in prod) with signed-URL access |
| 2FA | `mfa_method` modeled; pluggable second-factor interface |
| Reputation earning | `reputation` is a real attribute, seeded; earning deferred |
| Static/PDF maps | coordinate system is map-specific; geographic now, image-pixel interface present |

**Out of scope for Slice A:** registration/login UI, 2FA, password reset, admin UI, the D&D preset, native app, reputation earning, tenant resolution by subdomain.

## 8. Editable public demo & abuse limits

The deployed demo is **publicly editable without login** (an employer can play), which mandates guardrails from day one:

- **Editing surface:** visitors add/edit **notes on the seeded Boston map only** — **no map uploads** (removes the largest abuse surface).
- **Size caps:** max section length, max sections per note, max note payload — defeats the "10 GB note."
- **Rate/creation limits:** per-session + per-IP write throttling; cap on notes created per time window.
- **Total cap + reset:** bounded row count; **nightly reset** of demo data; a visible "sandbox — resets nightly" notice.
- **Guest identity:** a visitor acts as a **Contributor persona** (own notes public-by-default; may append to, not edit, seeded owner notes).

These guardrails are the **seam** for production rate-limiting/abuse protection.

## 9. Multi-tenancy & isolation

Shared schema + `tenant_id` on every domain row, threaded from day one. Enforcement target is **Postgres Row-Level Security** (enabled with auth). IDOR prevention runs through the same policy layer as the visibility engine. Cross-tenant isolation is covered by an always-green **authorization test suite** ("a viewer in tenant A can never read tenant B").

## 10. Engineering process & quality (cross-cutting, from PR #1)

- **PR definition-of-done:** every PR bundles **code + documentation + tests** together — docs updated simultaneously; tests created/modified/deleted as needed.
- **PR provenance & reasoning:** a PR template requires **Summary · Files changed (created/modified/deleted) · Provenance (agent / model / version) · Reasoning & alternatives · Testing · Risk & rollback.** CI fails PRs with empty/placeholder sections; the file-change list is auto-generated from the diff; model/version captured via commit trailer. Reasoning links to ADRs.
- **ADR log** (`docs/adr/`): records each deferral/decision (PWA-not-native, Django-Ninja, RLS, seeded-reputation, hosting platform, …) so the seniority of the deferrals is legible.
- **CI/CD** (GitHub Actions): lint, type-check (mypy + TS), test, build, deploy; **dependency scanning + secret scanning + SAST**; SBOM; lockfiles; Dependabot/Renovate.
- **Per-PR preview environments** (live URL per PR), pairing with the PR rigor; Neon DB branching for isolated preview data.
- **Observability:** structured logging with tenant/user/correlation context, error tracking (Sentry), health-check endpoint.
- **Security posture:** a written **STRIDE threat model** mapped to the authorization test suite; security headers (CSP/HSTS); secrets via env/secret store; TLS; provider encryption at rest.
- **Infrastructure as Code:** environment + services declared (e.g. render.yaml / fly.toml / Terraform); dev/staging/prod separation with seed data.

## 11. Testing strategy

- **Unit** — domain logic, especially the visibility engine.
- **Property-based** — visibility engine invariants over generated viewers/sections.
- **Integration** — API endpoints against a real Postgres (incl. RLS once enabled).
- **Authorization suite** — first-class, always green: cross-tenant isolation, private-never-leaks, teaser-vs-invisible, contributor-cannot-edit-owner.
- **E2E** — core flows (place note, set per-section visibility, switch viewer, bulk-label, revise/soft-delete) via the PWA.
- **Frontend** — component tests; accessibility checks on map controls.

## 12. Cost & hosting recipe

~$7/mo: app+worker instance (~$7) · Neon Postgres (free) · Cloudflare R2 (free) · Cloudflare Pages (free) · Resend/SES email (free) · OpenFreeMap/MapTiler free tiles. Final platform choice recorded in an ADR.

## 13. Open assumptions to confirm (at the review gate)

1. ★ **Reputation seeded in Slice A, earning deferred** — confirm this split.
2. **Labels are the durable grouping primitive; regions provide spatial *selection* into the same bulk path** — confirm vs. wanting regions to be first-class persistent groups.
3. **Demo guests act as Contributors (append-only on owner notes)** — confirm capability model.
4. **Three view-switcher personas** (Owner / Contributor / reputation-bearing Viewer) sufficient for the demo, or more?

## 14. Non-goals

Real authentication, 2FA, admin UI, the D&D preset, native mobile, reputation earning, and tenant-resolution-by-subdomain are explicitly **not** in Slice A — each is a named, seamed, deferred slice.
