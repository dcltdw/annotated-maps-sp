# A4 — Public Sandbox Demo — Design

- **Status:** approved (brainstorming) — 2026-06-18
- **Goal:** Deploy the existing point-note app as a **live public sandbox** (Render + Neon/PostGIS). Visitors explore the seeded Boston map, flip personas (`preview_as`) to watch section-level visibility, and may create/edit/append content that auto-expires after 7 days. A token-gated moderation page lets the owner prune abuse. **No real auth** — `preview_as` remains the display + visibility identity (A5 replaces it later).
- **Relationship:** sits between the merged point-note core (foundation → A1.3c + hardening) and A5 (real auth). Chosen as the fastest path to the biggest portfolio multiplier — a clickable live URL — deferring the auth/RLS lift. Builds on the foundation deploy skeleton (`render.yaml`, `backend/Dockerfile`, `django-environ` settings, `corsheaders`, prod security block, DB sessions, `seed_demo`), which was never deployed.
- **Ships as two PRs under this one spec:** **A4a** (sandbox behavior + actual deploy) then **A4b** (moderation page) — get the demo live and validated before building the tool to police it.

## Sandbox model (env-gated)

A `SANDBOX_MODE` flag gates every sandbox behavior below:

```python
SANDBOX_MODE = env.bool("SANDBOX_MODE", default=False)
```

Default **False** → local dev and the existing test suite behave exactly as today. **True** only on the deployed environment. This keeps every existing test green without modification and isolates all new behavior behind one switch.

**Seed vs ephemeral content.** New fields on `Note` (one migration, `0004`):
- `is_seed = models.BooleanField(default=False)` — `seed_demo` sets `True` on everything it creates; the API always creates with `False` (default). Safe default: nothing is accidentally permanent.
- `session_key = models.CharField(max_length=40, blank=True, default="")` — the Django session that created an ephemeral note.
- `created_ip = models.GenericIPAddressField(null=True, blank=True)` — the client IP that created it.

Appends are `Note` rows (self-FK `parent`), so they inherit all three fields automatically.

**Seed protection.** In sandbox mode, `update_note`/`update_append`/`delete_note` raise `403` when the target's `is_seed` is True. The Boston seed is immutable — no persona switch can corrupt the permanent demo (there is no daily reset to restore it).

**Session ownership.** In sandbox mode, edit/delete is allowed only when the note is ephemeral **and** `note.session_key == request.session.session_key`. A visitor's session owns what it created, independent of which persona they're currently "viewing as". A session is ensured at write time:

```python
if not request.session.session_key:
    request.session.create()
```

Outside sandbox mode the existing rule (`note.author_id == preview_as` → else 403) is untouched.

**Server-computed `editable`.** `NoteOut` and `AppendOut` gain `editable: bool`, computed server-side per viewer/session:
- sandbox: `not is_seed and session_key == request.session.session_key`
- non-sandbox: `author_id == preview_as`

The frontend renders edit/delete affordances from `editable` instead of recomputing `author_id === previewAs` locally. This is the one change to the existing read contract; it is additive (a new field) and replaces a frontend heuristic with an authoritative server value — a clean seam for A5.

**Guests still cannot write.** Creating requires a non-guest `preview_as` (existing rule); session ownership operates among chosen personas.

## Limits (sandbox only)

Enforced in `create_note`/`create_append` when `SANDBOX_MODE`:
- **Per session:** ≤ 15 outstanding ephemeral top-level notes; ≤ 30 ephemeral appends (count `session_key == current, is_seed=False`, split by `parent__isnull`).
- **Per IP:** ≤ 30 ephemeral creates per rolling hour (`created_ip == client_ip, created_at >= now − 1h`). Client IP via a `client_ip(request)` helper: first hop of `HTTP_X_FORWARDED_FOR` (Render terminates TLS at its proxy), else `REMOTE_ADDR`.
- **Global backstop:** ≤ 2,000 total ephemeral rows (`is_seed=False`); beyond it, creation is refused until the reaper drains it — protects the small free Neon DB.

Each breach returns a clear error the frontend surfaces: `429` for the rate/quantity caps, with a `{"detail": "Sandbox limit reached — …"}` body. (Per-session and global use `429` too for consistency.)

## 7-day TTL reaper

Ephemeral content (`is_seed=False`) is **hard-deleted** 7 days after `created_at`. Deleting a parent note cascades to its appends (FK `on_delete=CASCADE`); a stale append whose parent is still alive is reaped on its own.

- Management command `reap_ephemeral` (in `maps/management/commands/`): deletes `Note.all_objects.filter(is_seed=False, created_at__lt=now − 7d)`, logs the deleted count. Uses `all_objects` so already-soft-deleted rows are also purged. Idempotent.
- Scheduled **daily via a Render Cron service** added to `render.yaml` (`type: cron`, same Docker image, `schedule:` daily, command `uv run python manage.py reap_ephemeral`).
- **Fallback:** if Render Cron is not available on the chosen plan, the command is invoked by an external scheduler hitting it (documented in the README); the lazy-on-read approach is explicitly rejected (no writes inside GET handlers).

## Health + deploy wiring (PR A4a)

- **Health endpoint:** `GET /api/v1/health` → `{"status": "ok", "version": API_VERSION, "git_sha": GIT_SHA}` after a light `SELECT 1` (returns 503 if the DB is unreachable). Matches the existing `render.yaml` `healthCheckPath: /api/v1/health`.
- **`render.yaml`:** add env vars `SANDBOX_MODE=true`, `MOD_TOKEN` (`sync:false`), `CORS_ALLOWED_ORIGINS` (`sync:false`), cross-site cookie settings as needed; add the cron service; seed once on first deploy (a `seed_demo` run guarded to be idempotent / no-op if the demo tenant already exists).
- **Cross-origin cookies** (API and web are separate Render domains): `CORS_ALLOW_CREDENTIALS = True`, `CORS_ALLOWED_ORIGINS` = the web origin (no wildcard with credentials), `SESSION_COOKIE_SAMESITE = "None"`, `SESSION_COOKIE_SECURE = True` (prod). Frontend write/read calls that rely on the session use `fetch(..., { credentials: "include" })`.
- **Neon:** create the project, enable the `postgis` extension (`CREATE EXTENSION postgis;`), set `DATABASE_URL`. `DJANGO_ALLOWED_HOSTS` = the API domain; `VITE_API_BASE` = the API origin.
- **Frontend:** a small persistent banner — "Sandbox — anyone can edit; content resets after 7 days" — and surfacing of the `429`/`403` sandbox-limit errors in the existing editor error path.
- **Deploy + smoke-test** the live URL: health, list notes, create-as-persona → it appears, persona switch shows visibility changing, hit a cap, confirm the banner.

## Moderation page (PR A4b)

Token-gated endpoints (a `X-Mod-Token` header compared **constant-time** to the `MOD_TOKEN` env var; `401` otherwise; HTTPS-only; the token is never logged):
- `GET /api/v1/mod/recent?limit=` → recent ephemeral notes + appends ordered by `updated_at` desc: `id`, `kind` ("note"/"append"), title/snippet, author persona name, **truncated** `session_key`, `created_ip`, `created_at`, `updated_at`, `version`, map name.
- `POST /api/v1/mod/delete` → body is exactly one of `{ids:[…]}`, `{session_key}`, `{created_ip}` → hard-deletes the matching **ephemeral** rows (a guard ensures `is_seed=False` is never violated); returns the deleted count.

These fields (`session_key`, `created_ip`) are exposed **only** through the token-gated mod endpoints, never through the public note API.

- **Frontend:** an unlisted React `/moderate` route — prompts for the token (held in memory / `sessionStorage`, never in the bundle, sent as the header), shows a table with per-row checkboxes + "delete selected", plus group actions "delete all from this session" / "delete all from this IP". Confirm dialogs on every delete.
- **Audit:** each mod delete writes an `AuditEvent` (`action="mod.delete"`, `metadata` = the criterion + count). Reuses the existing append-only model.

## Testing

- **Backend** (`SANDBOX_MODE` toggled per test): seed-protection (edit/delete seed → 403), session-ownership (own-session ephemeral edit/delete OK; other-session → 403), the three caps (session quantity, per-IP hourly rate, global backstop → 429), the reaper (deletes `>7d` ephemeral, keeps seed and recent), `editable` flag both modes, health (200 ok / 503 on DB down), mod endpoints (401 without/with bad token; 200 with; delete by ids/session/ip; **never** deletes seed). Existing tests stay green unmodified (flag defaults False).
- **Frontend:** limit-error surfacing in the editor; moderation page (token prompt gate, list render, delete calls) against the stateful stub; the sandbox banner renders.
- **Deploy:** manual live smoke-test (above). `ruff`/`format`/`mypy`/`makemigrations --check`; `npm run lint`/`test`/`build`.

## Out of scope

Real auth / user accounts (A5 — replaces `preview_as`); region/boundary notes (A2); revision history (edits still hard-replace sections); multi-tenant RLS; heavyweight rate-limit / captcha libraries (the simple counters suffice for a low-traffic portfolio demo); making the `e2e` job a required CI gate.

## Sequencing

- **PR A4a — Safe sandbox + go live:** `Note` fields + migration `0004`; `seed_demo` sets `is_seed`; `SANDBOX_MODE` behaviors (seed protection, session ownership, `editable`, the three caps); `client_ip` helper; `reap_ephemeral` command + cron; `/api/v1/health`; `render.yaml` + CORS/cookie settings; frontend banner + limit-error surfacing; **deploy + smoke-test**.
- **PR A4b — Moderation:** `mod/recent` + `mod/delete` endpoints + token guard; the `/moderate` React route; `AuditEvent` logging; tests.
