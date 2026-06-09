# Annotated Maps — Design Spec

- **Date:** 2026-06-08
- **Status:** Draft for review
- **Revision:** r1 — incorporates review round 1 (layers + multi-region membership, Private split, demo trivial-auth + 7-day lifecycle, read-only guests). · r2 — adds the production-lenses doc + foundation seams (PostGIS, etc.); see §15.
- **Scope of this document:** the full production target as the north star, and the detailed design of **Slice A** (the first buildable slice).

---

## 1. Purpose & goals

Annotated Maps lets a curator place richly-permissioned notes on a map — a real-world slippy map or a static image/PDF — and control, per note and per *section within a note*, exactly who can see what.

Two goals drive the project:

1. **Portfolio piece.** A publicly hosted, polished, production-shaped app that demonstrates senior+ engineering breadth (security, multi-tenancy, API design, testing rigor, operable infrastructure, disciplined process).
2. **Personally useful.** Ultimately a GM's tool for D&D campaign maps. The public demo, however, is a **real-world Boston map with real notes** (favorite restaurants, running routes), because that is instantly legible to employers.

The product is **domain-neutral**: D&D and "places I love around Boston" are two *presets* over one engine, not two apps.

## 2. Product concept & presets

- **Maps** hold **notes**. A note may be **anchored** to a **point**, a drawn **region/boundary**, the **whole map**, or **nothing** (free-floating "plot notes"); independently of its anchor it may belong to **multiple regions** and **multiple layers** for organization and display.
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
| Database | **PostgreSQL** + **PostGIS** (geometry as GeoJSON/WKB), with **Row-Level Security** as the tenant-isolation enforcement (switched on with auth; `tenant_id` column threaded from day one) |
| Async | **Postgres-backed task queue (Procrastinate)** — no Redis, no extra cost; behind an `EmailSender`/job interface |
| Object storage | **S3-compatible (Cloudflare R2)** for map files, served via short-lived **signed URLs**; behind a storage interface (local in dev) |
| Auth strategy | **Self-implemented on vetted libraries.** Slice A ships a **trivial** username+password registration/login for the public demo; production-grade auth (email verification, 2FA, reset, lockout, full RBAC) replaces it later behind the same seam |
| Clients | Web/mobile via responsive PWA now; **native app deferred**, enabled by the API-first boundary |

**Hosting target (~$7/mo):** always-on small app instance (Render/Railway/Fly) · Neon free Postgres · Cloudflare R2 free tier · static PWA on Cloudflare Pages · Resend/SES free email. Tunable; final platform pinned in an ADR.

## 4. Decomposition & roadmap

The project is **decomposed into slices**, each its own spec → plan → build cycle. Slice A is large but coherent; its **implementation plan is internally phased** with review checkpoints.

**Slice A — Core annotated-maps product (this spec).** Internal phases:

- **A1** — Map + point notes + the visibility engine (4 rule types, section-level, teasers) + the identity model (seeded users; "preview as" affordance).
- **A2** — Regions/boundaries (drawing + region-anchored notes + multi-region membership + spatial selection helper).
- **A3** — Labels + layers + authorization-aware bulk operations.
- **A4** — Note revisions/history + soft delete + optimistic concurrency.
- **A5** — Editable public demo: **trivial registration/login, read-only guests, 7-day account+data lifecycle**, abuse limits, deploy + CI/CD + preview envs.

**Deferred slices (production target, each with a Slice-A seam):**

- **Production auth hardening** — email verification, password reset, **pluggable** 2FA (email OTP first; TOTP/WebAuthn later), brute-force protection, full RBAC via per-tenant memberships (replaces Slice A's trivial auth).
- **Multi-tenancy hardening** — RLS policies enabled, tenant resolution (subdomain/path), cross-tenant IDOR audit.
- **Reputation earning** — upvotes/scoring that *produce* the reputation attribute the gate already consumes.
- **D&D preset** — static/PDF maps, image-pixel coordinates, "Arcana ≥ X" gate UI, campaign ergonomics.
- **Native mobile client** — thin client over the existing API.
- **Admin** — platform/tenant administration (Django admin as a head start), per-tenant settings/feature-flags (generalizing admin-configurable 2FA).
- **Operational depth** — backups/DR + runbook, distributed tracing, SLOs, PII export/deletion.

## 5. Domain model

Neutral vocabulary (D&D/real-world terms are presentation-layer labels over these):

- **Tenant (Game/Space)** — the multi-tenancy boundary. Every domain row carries `tenant_id` from day one.
- **User** — an identity. In Slice A, users are either seeded or created via trivial registration; carries attributes including **`reputation`** (seeded in Slice A). A **Guest** is an unauthenticated visitor with **read-only** access.
- **Membership** — `(user, tenant, role)`. Roles: **Owner/Curator**, **Contributor**, **Viewer**. (A user may hold different roles in different tenants.)
- **Group** — a named audience within a tenant (e.g. "Running club"); has members; **may include the owner** (this is how to share privately with a chosen circle).
- **Map** — belongs to a tenant; a slippy map (geographic CRS) or a static image/PDF (image-pixel CRS, later). References a map file in object storage.
- **Note** — belongs to a map; carries `author_id`; **anchored** to a **point**, a **region**, the **whole map**, or **nothing**. Independently of its anchor, a note may **belong to multiple regions** and appear on **multiple layers**. Soft-deletable; revisioned.
- **Section** — an ordered part of a note; holds content and **one VisibilityRule**; teaser flag (default off → invisible).
- **Append** — a first-class note attached to a parent note (its own author, visibility, sections); rendered inline; never mutates the parent.
- **Collection** — the **unified grouping primitive**: a note belongs to **many collections**, and one membership mechanism + one **authorization-aware bulk-operation path** serve all of them. Each collection has a **`kind`**:
  - **label** — a lightweight tenant-scoped **tag**.
  - **layer** — a **toggleable display** grouping (e.g. "Restaurants", "Running routes", "Secrets"); controls visualization, **not** permission.
  - **region/boundary** — adds **geometry** (PostGIS, GeoJSON/WKB); membership may be explicit or **derived from a point falling inside** (spatial query); also anchors notes and acts as a **spatial selector**.

  Kind-specific attributes (region geometry, layer toggle state) hang off the base collection.

## 6. The visibility engine

A pure domain service: `canView(viewer, section) → { visible | teaser | hidden }`, evaluated per section. It is **content authorization**, kept deliberately separate from **access authentication**, and routed through a single **centralized policy layer** (no scattered role checks).

**Four visibility rule types:**

| Rule | Visible when… | Real-world | D&D |
|---|---|---|---|
| **Public** | always | everyone | everyone |
| **Audience** | viewer is a listed user or a member of a listed group | "Friends", "Running club" | a party/faction |
| **Attribute gate** | a viewer attribute meets a threshold | **reputation ≥ N**, age ≥ 21, verified | **Arcana ≥ X** |
| **Private** | viewer **is the owner — and no one else** | strictly owner | strictly GM |

**Private vs. a private group.** *Private* means **owner-only — not other curators, not contributors.** "Share secretly with a chosen few (including me)" is **not** Private; it is an **Audience** rule whose group's members include the owner. The UI keeps these distinct to avoid the common conflation. **Admin access to Private content** is a separate, **explicit, audited** policy (default **deny**) — see §13.

**Teaser behavior:** restricted sections are **fully invisible by default**. A section may opt into a **teaser** — a redacted placeholder revealing that hidden content exists. Configurable per section.

**Viewer-resolution seam:** all access flows through one "resolve current tenant + current viewer (role, group memberships, attributes)" function — backed by the trivial login in the deployed demo, by a "preview as" affordance in dev, and by production sessions later. The "preview as" affordance is retained as a QA/demo tool for the engine.

**Testing:** the engine is a pure function of `viewer × section`, making it the ideal target for **property-based tests** (e.g. "a Private section is never visible to a non-owner under any generated viewer").

## 7. Slice A scope

**In scope (built):** real Boston slippy map; point + region notes + whole-map + free-floating notes; sections with all four visibility rules; per-section teaser; contributor notes + appends (visually distinct); labels / layers / regions as a unified **Collection** model with one authorization-aware bulk-op path; multi-region membership + spatial selection; note revisions/history + soft delete + optimistic concurrency (version field); **trivial registration/login with read-only guests**; OpenAPI + typed client; CI/CD; per-PR preview environments.

**Seamed (stubbed, architected-for):**

| Deferred capability | Slice A seam |
|---|---|
| Production auth (email verify, 2FA, reset, lockout, full RBAC) | Slice A ships **trivial** username+password registration/login behind the auth seam; production-grade auth replaces it later. Dev uses a "preview as" switcher. |
| Multi-tenancy isolation | `tenant_id` on every row; single seeded tenant; RLS policies added later |
| Email (verification/OTP/reset) | all sends go through an `EmailSender` interface (console/no-op in A) |
| Object storage | storage interface (local in dev → R2 in prod) with signed-URL access |
| 2FA | `mfa_method` modeled; pluggable second-factor interface |
| Reputation earning | `reputation` is a real attribute, seeded; earning deferred |
| Static/PDF maps | coordinate system is map-specific; geographic now, image-pixel interface present |

**Out of scope for Slice A:** production-grade auth (email verification, 2FA, reset, lockout), admin UI, the D&D preset, native app, reputation earning, tenant resolution by subdomain.

## 8. Editable public demo & abuse limits

The deployed demo is **publicly viewable** and **editable after a trivial sign-up**, so an employer can both browse and play. Guardrails from day one:

- **Accounts:** **trivial registration + login** (username + password; no email verification or 2FA). **Guests (not logged in) have read-only access.** Registering makes you a **Contributor**.
- **7-day lifecycle:** demo accounts **and the data they create are wiped 7 days after creation** (rolling, per account), with a visible "demo account — your data is removed after 7 days" notice. Replaces a global nightly reset, so a returning visitor still finds their work.
- **Editing surface:** logged-in visitors add/edit **their own notes on the seeded Boston map only** — **no map uploads** (removes the largest abuse surface); they may **append** to (not edit) seeded owner notes.
- **Size caps:** max section length, max sections per note, max note payload — defeats the "10 GB note."
- **Rate/creation limits:** per-account + per-IP write throttling; cap on notes created per time window; **registration rate-limited per IP** with minimal bot resistance.

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
- **Authorization suite** — first-class, always green: cross-tenant isolation, private-never-leaks, teaser-vs-invisible, contributor-cannot-edit-owner, guest-is-read-only.
- **E2E** — core flows (register/login, place note, set per-section visibility, preview as another viewer, bulk-label, revise/soft-delete) via the PWA.
- **Frontend** — component tests; accessibility checks on map controls.

## 12. Cost & hosting recipe

~$7/mo: app+worker instance (~$7) · Neon Postgres (free) · Cloudflare R2 (free) · Cloudflare Pages (free) · Resend/SES email (free) · OpenFreeMap/MapTiler free tiles. Final platform choice recorded in an ADR.

## 13. Decisions & open items

**Resolved in review round 1:**

- Reputation is **seeded** in Slice A; earning **deferred**.
- **Guests (not logged in) have read-only access**; editing requires trivial registration.
- Demo lifecycle: **7-day rolling wipe** of accounts + their data (not nightly).
- Notes may belong to **multiple layers and multiple regions**; **Private** is split from "shared private group" (an Audience whose group includes the owner).
- The 4-slice/deferred split and the engineering-process section: **confirmed.**
- Grouping: a **unified Collection** primitive — Label / Layer / Region are *kinds*; one membership mechanism + one authorization-aware bulk-op path.

**Open (non-blocking for Slice A):**

1. **Admin access to Private content:** default **deny** for now; whether tenant admins may *ever* read Private notes (audited, for moderation) or never is settled when the **Admin slice** is designed.
2. **Preview personas:** Owner / Contributor (in-group vs not) / reputation-bearing (≥N vs &lt;N) / **Guest (read-only)** — exact preview set finalized in A1/A5.

## 14. Non-goals (Slice A)

Production-grade authentication (email verification, 2FA, reset, lockout), admin UI, the D&D preset, native mobile, reputation earning, and tenant-resolution-by-subdomain are explicitly **not** in Slice A — each is a named, seamed, deferred slice.

## 15. Production lenses & foundation seams

The full catalogue of big-picture lenses a production version must address — security, scalability (scale **out**, not up), reliability, observability, data governance/compliance, i18n/a11y, interoperability, mobile/offline, and business/legal — lives in **`docs/architecture/production-lenses.md`**, triaged into *foundation-now / seam-and-defer / note-and-revisit*. Most are out of Slice A by design.

The following **foundation-now seams** are cheap structural choices that are painful to retrofit, so Slice A's groundwork **builds them in** (only PostGIS is a genuine scope addition; the rest are disciplines/structure):

1. **PostGIS + GeoJSON/WKB** geometry  ·  2. stateless app tier + connection pooling  ·  3. **API versioning under `/api/v1`**  ·  4. observability context (request/tenant/user IDs in structured logs)  ·  5. **expand-contract migrations from migration #1**  ·  6. GDPR-able delete/export mechanism (generalizing the 7-day demo purge)  ·  7. idempotency + optimistic concurrency (version field)  ·  8. i18n structure + a11y "never color alone"  ·  9. **OSM/ODbL attribution & licensing**  ·  10. audit-log seam.
