# A4a — Public Sandbox + Go Live — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing point-note app safe to expose publicly (env-gated sandbox mode: seed protection, session-scoped write ownership, creation caps, a 7-day TTL reaper) and deploy it live on Render + Neon.

**Architecture:** All new behavior hides behind `settings.SANDBOX_MODE` (default False → local dev + the existing 91-test suite are untouched). Content is tagged `is_seed` (permanent, written by `seed_demo`) vs ephemeral (visitor-created, stamped with `session_key`/`created_ip`, auto-reaped at 7 days). A small `maps/sandbox.py` module centralizes the sandbox rules; the existing write endpoints call into it. The deploy reuses the foundation skeleton (`render.yaml`, `Dockerfile`).

**Tech Stack:** Django 5 + Django-Ninja + PostGIS, pytest; React + TS (Vite); Render (Docker web + static + cron) + Neon (Postgres/PostGIS).

**Spec:** `docs/superpowers/specs/2026-06-18-a4-public-sandbox-demo-design.md`. This is **PR A4a**; the moderation page is the separate **A4b** plan after this merges.

**Conventions:** backend from `backend/`, `uv run …`; DB up via `docker compose up -d db` + wait for `pg_isready`. After editing any test file, run `uv run ruff format --check .` over the **whole** backend dir. Frontend from `frontend/`.

---

## Task 1: `Note` sandbox fields + migration + seed marking

**Files:**
- Modify: `backend/maps/models.py` (the `Note` model)
- Modify: `backend/maps/seed.py` (mark the seed note)
- Create: `backend/maps/migrations/0004_note_sandbox_fields.py` (generated)
- Test: `backend/maps/tests/test_models.py`

- [ ] **Step 1: Write the failing test** — append to `backend/maps/tests/test_models.py`:

```python
def test_note_sandbox_fields_default_to_ephemeral(db):
    from django.contrib.gis.geos import Point
    from core.models import Tenant, User
    from maps.models import Map, Note

    t = Tenant.objects.create(name="T", slug="t")
    u = User.objects.create(display_name="U")
    m = Map.objects.create(tenant=t, name="M", center=Point(0, 0))
    n = Note.objects.create(tenant=t, map=m, author=u, title="x", point=Point(0, 0))
    assert n.is_seed is False          # safe default: nothing is accidentally permanent
    assert n.session_key == ""
    assert n.created_ip is None
```

- [ ] **Step 2: Run — expect FAIL** (`is_seed` doesn't exist): `uv run pytest maps/tests/test_models.py -k sandbox_fields -v`

- [ ] **Step 3: Add the fields** to the `Note` model in `backend/maps/models.py` (after `point`):

```python
    # --- Sandbox/demo metadata (only meaningful when settings.SANDBOX_MODE) ---
    is_seed = models.BooleanField(default=False)  # True only for seed_demo content (permanent, read-only)
    session_key = models.CharField(max_length=40, blank=True, default="")  # creator's session (ephemeral only)
    created_ip = models.GenericIPAddressField(null=True, blank=True)  # creator's IP (ephemeral only)
```

- [ ] **Step 4: Mark the seed note** in `backend/maps/seed.py` — add `"is_seed": True` to the note's `get_or_create` defaults so only the seed note is permanent (visitors write to the same tenant/map, so a blanket update would wrongly freeze their content):

```python
    note, created = Note.objects.get_or_create(
        tenant=tenant,
        map=the_map,
        author=owner,
        title="Castle Island — Pleasure Bay Loop",
        defaults={"point": Point(-71.0136, 42.3380), "is_seed": True},
    )
```

- [ ] **Step 5: Generate the migration**: `uv run python manage.py makemigrations maps --name note_sandbox_fields` (expect `0004_note_sandbox_fields.py` creating 3 fields).

- [ ] **Step 6: Run — expect PASS** + whole suite green (defaults don't change existing behavior): `uv run pytest`

- [ ] **Step 7: Checks + commit:** `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run python manage.py makemigrations --check --dry-run`

```bash
git add maps/models.py maps/seed.py maps/migrations/0004_note_sandbox_fields.py maps/tests/test_models.py
git commit -m "feat(a4a): Note sandbox fields (is_seed/session_key/created_ip) + seed marking"
```

---

## Task 2: `SANDBOX_MODE` setting + `maps/sandbox.py` helpers

**Files:**
- Modify: `backend/annotated_maps/settings.py` (add the flag)
- Create: `backend/maps/sandbox.py`
- Create: `backend/maps/tests/conftest.py` (shared `world` fixture for sandbox tests)
- Test: `backend/maps/tests/test_sandbox.py`

- [ ] **Step 1: Add the flag** to `backend/annotated_maps/settings.py`, immediately after the `DEBUG = env(...)` line (around line 28):

```python
# Public-demo sandbox behaviour (seed protection, session ownership, creation caps,
# TTL reaper). OFF by default so local dev + tests behave like a normal app.
SANDBOX_MODE = env.bool("SANDBOX_MODE", default=False)
```

- [ ] **Step 2: Create the shared fixture** `backend/maps/tests/conftest.py`:

```python
import pytest
from django.contrib.gis.geos import Point

from core.models import Tenant, User
from maps.models import Map, Note, Section


@pytest.fixture
def world(db):
    """A minimal demo world: one tenant/map, two personas, and one SEED note."""
    tenant = Tenant.objects.create(name="Demo", slug="demo")
    alice = User.objects.create(display_name="Alice", reputation=50)
    bob = User.objects.create(display_name="Bob", reputation=10)
    the_map = Map.objects.create(tenant=tenant, name="Demo", center=Point(-71.06, 42.36))
    seed = Note.objects.create(
        tenant=tenant, map=the_map, author=alice, title="Seed",
        point=Point(-71.0, 42.3), is_seed=True,
    )
    Section.objects.create(note=seed, order=0, content="public", rule_type=Section.RuleType.PUBLIC)
    return {"tenant": tenant, "map": the_map, "alice": alice, "bob": bob, "seed": seed}
```

- [ ] **Step 3: Write the failing test** for the one pure helper — `backend/maps/tests/test_sandbox.py`:

```python
from django.test import RequestFactory

from maps.sandbox import client_ip


def test_client_ip_prefers_first_forwarded_for_hop():
    req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1", REMOTE_ADDR="10.0.0.1")
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_falls_back_to_remote_addr():
    req = RequestFactory().get("/", REMOTE_ADDR="198.51.100.4")
    assert client_ip(req) == "198.51.100.4"
```

- [ ] **Step 4: Run — expect FAIL** (no module): `uv run pytest maps/tests/test_sandbox.py -v`

- [ ] **Step 5: Create** `backend/maps/sandbox.py`:

```python
"""Sandbox-mode behaviour for the public demo deploy. Everything here is gated by
settings.SANDBOX_MODE (default False → local dev + tests behave like a normal app)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from ninja.errors import HttpError

from maps.models import Note

# Per-deploy caps (only enforced when SANDBOX_MODE).
MAX_NOTES_PER_SESSION = 15
MAX_APPENDS_PER_SESSION = 30
MAX_CREATES_PER_IP_PER_HOUR = 30
MAX_EPHEMERAL_ROWS = 2000


def client_ip(request: HttpRequest) -> str:
    """Best-effort client IP. Render terminates TLS at its proxy, so the real client
    is the first hop of X-Forwarded-For; fall back to REMOTE_ADDR."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def ensure_session(request: HttpRequest) -> str:
    """Return the session key, creating a session row if none exists yet."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def is_editable(request: HttpRequest, note: Note, preview_as: UUID | None) -> bool:
    """Whether the caller may edit/delete `note` (drives the read API's `editable`)."""
    if settings.SANDBOX_MODE:
        sk = request.session.session_key
        return (not note.is_seed) and bool(sk) and note.session_key == sk
    return note.author_id == preview_as


def authorize_write(request: HttpRequest, note: Note, preview_as: UUID | None, noun: str = "note") -> None:
    """Raise HttpError if the caller may not edit/delete `note`."""
    if settings.SANDBOX_MODE:
        if note.is_seed:
            raise HttpError(403, "The demo content is read-only.")
        sk = request.session.session_key
        if not sk or note.session_key != sk:
            raise HttpError(403, "You can only change content you created in this session.")
    else:
        if preview_as is None or note.author_id != preview_as:
            raise HttpError(403, f"You can only edit your own {noun}s.")


def enforce_create_limits(request: HttpRequest, *, is_append: bool) -> tuple[str, str]:
    """Enforce sandbox creation caps and return (session_key, client_ip) to stamp on
    the new row. Raises HttpError(429) when a cap is hit. Caller guards on SANDBOX_MODE."""
    session_key = ensure_session(request)
    ip = client_ip(request)
    if Note.objects.filter(is_seed=False).count() >= MAX_EPHEMERAL_ROWS:
        raise HttpError(429, "The sandbox is full right now — content is pruned after 7 days. Try again later.")
    hour_ago = timezone.now() - timedelta(hours=1)
    if Note.objects.filter(is_seed=False, created_ip=ip, created_at__gte=hour_ago).count() >= MAX_CREATES_PER_IP_PER_HOUR:
        raise HttpError(429, "Too many additions from your network this hour — please slow down.")
    session_qs = Note.objects.filter(is_seed=False, session_key=session_key)
    if is_append:
        if session_qs.filter(parent__isnull=False).count() >= MAX_APPENDS_PER_SESSION:
            raise HttpError(429, "You've reached this session's append limit for the sandbox.")
    elif session_qs.filter(parent__isnull=True).count() >= MAX_NOTES_PER_SESSION:
        raise HttpError(429, "You've reached this session's note limit for the sandbox.")
    return session_key, ip
```

- [ ] **Step 6: Run — expect PASS:** `uv run pytest maps/tests/test_sandbox.py -v`

- [ ] **Step 7: Checks + commit:** `uv run ruff check . && uv run ruff format --check . && uv run mypy .`

```bash
git add annotated_maps/settings.py maps/sandbox.py maps/tests/conftest.py maps/tests/test_sandbox.py
git commit -m "feat(a4a): SANDBOX_MODE flag + maps/sandbox helpers (ip/session/authz/limits)"
```

---

## Task 3: Sandbox write authorization (seed protection + session ownership)

Wire `authorize_write` into the three write paths so that, in sandbox mode, the seed is read-only and a visitor may only edit/delete what their own session created. Non-sandbox behavior is unchanged.

**Files:**
- Modify: `backend/maps/api.py` (`note_for_edit`, `delete_note`, `update_note`, `update_append`)
- Test: `backend/maps/tests/test_sandbox.py`

- [ ] **Step 1: Write failing tests** — append to `backend/maps/tests/test_sandbox.py`:

```python
import json

from django.test import Client


def _create_note(client, world, author, title="mine"):
    payload = {"title": title, "lng": -71.05, "lat": 42.35,
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}]}
    r = client.post(f"/api/v1/maps/{world['map'].id}/notes?preview_as={author.id}",
        data=json.dumps(payload), content_type="application/json")
    assert r.status_code == 201, r.content
    return r.json()["id"]


def test_sandbox_seed_is_read_only(world, settings):
    settings.SANDBOX_MODE = True
    seed_id = world["seed"].id
    # Even "as" the seed's author, a visitor cannot delete the permanent seed.
    r = Client().delete(f"/api/v1/notes/{seed_id}?preview_as={world['alice'].id}")
    assert r.status_code == 403


def test_sandbox_session_owns_its_writes(world, settings):
    settings.SANDBOX_MODE = True
    owner = Client()  # one client == one session (cookies persist across its requests)
    note_id = _create_note(owner, world, world["alice"])
    # A different session (different Client) cannot delete it, even as the same persona.
    other = Client()
    assert other.delete(f"/api/v1/notes/{note_id}?preview_as={world['alice'].id}").status_code == 403
    # The owning session can.
    assert owner.delete(f"/api/v1/notes/{note_id}?preview_as={world['alice'].id}").status_code == 204
```

- [ ] **Step 2: Run — expect FAIL** (seed deletable / cross-session delete returns 204 today): `uv run pytest maps/tests/test_sandbox.py -k "seed_is_read_only or session_owns" -v`

- [ ] **Step 3: Import the helper** at the top of `backend/maps/api.py` (with the other maps imports):

```python
from maps.sandbox import authorize_write, enforce_create_limits, is_editable
```

- [ ] **Step 4: Replace the inline author checks** with `authorize_write` in the three handlers. In `note_for_edit` and `update_note`, replace:

```python
    if preview_as is None or note.author_id != preview_as:
        raise HttpError(403, "You can only edit your own notes.")
```
with:
```python
    authorize_write(request, note, preview_as, noun="note")
```

In `delete_note`, replace its `if preview_as is None or note.author_id != preview_as: raise HttpError(403, "You can only delete your own notes.")` with `authorize_write(request, note, preview_as, noun="note")`.

In `update_append`, replace its `if preview_as is None or append.author_id != preview_as: raise HttpError(403, "You can only edit your own appends.")` with `authorize_write(request, append, preview_as, noun="append")` — keep the subsequent `if append.parent_id is None: raise HttpError(400, "Not an append.")` guard exactly where it is (after the authz check).

- [ ] **Step 5: Run — expect PASS** + the whole suite (non-sandbox author tests still pass, since the message text is preserved — `"You can only edit your own notes."` / `"...appends."`; note `delete_note`'s message changes from "delete" to "edit" — if any existing test asserts the delete message text, update that assertion to the new wording, otherwise leave it): `uv run pytest`

- [ ] **Step 6: Checks + commit:** ruff/format/mypy clean.

```bash
git add maps/api.py maps/tests/test_sandbox.py
git commit -m "feat(a4a): sandbox write authz — seed read-only + session ownership"
```

---

## Task 4: Sandbox creation caps + session/IP stamping

**Files:**
- Modify: `backend/maps/api.py` (`create_note`, `create_append`)
- Test: `backend/maps/tests/test_sandbox.py`

- [ ] **Step 1: Write failing tests** — append to `backend/maps/tests/test_sandbox.py`:

```python
from maps.models import Note


def test_sandbox_per_session_note_cap(world, settings, monkeypatch):
    settings.SANDBOX_MODE = True
    import maps.sandbox as sb
    monkeypatch.setattr(sb, "MAX_NOTES_PER_SESSION", 2)  # keep the test fast
    c = Client()
    _create_note(c, world, world["alice"])
    _create_note(c, world, world["alice"])
    # third create in the same session is refused
    payload = {"title": "third", "lng": -71.05, "lat": 42.35,
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}]}
    r = c.post(f"/api/v1/maps/{world['map'].id}/notes?preview_as={world['alice'].id}",
        data=json.dumps(payload), content_type="application/json")
    assert r.status_code == 429


def test_sandbox_stamps_session_and_ip_on_create(world, settings):
    settings.SANDBOX_MODE = True
    note_id = _create_note(Client(), world, world["alice"])
    n = Note.objects.get(id=note_id)
    assert n.is_seed is False and n.session_key != "" and n.created_ip is not None


def test_non_sandbox_create_is_uncapped_and_unstamped(world, settings):
    settings.SANDBOX_MODE = False
    note_id = _create_note(Client(), world, world["alice"])
    n = Note.objects.get(id=note_id)
    assert n.session_key == "" and n.created_ip is None
```

- [ ] **Step 2: Run — expect FAIL:** `uv run pytest maps/tests/test_sandbox.py -k "per_session_note_cap or stamps_session" -v`

- [ ] **Step 3: Add cap-enforcement + stamping** in `create_note`. After `author = get_object_or_404(User, id=preview_as)` and before `note = Note.objects.create(...)`:

```python
    session_key, created_ip = "", None
    if settings.SANDBOX_MODE:
        session_key, created_ip = enforce_create_limits(request, is_append=False)
```
and add `session_key=session_key, created_ip=created_ip,` to the `Note.objects.create(...)` kwargs.

- [ ] **Step 4: Same for `create_append`** — after `author = get_object_or_404(User, id=preview_as)` and before `append = Note.objects.create(...)`:

```python
    session_key, created_ip = "", None
    if settings.SANDBOX_MODE:
        session_key, created_ip = enforce_create_limits(request, is_append=True)
```
and add `session_key=session_key, created_ip=created_ip,` to that `Note.objects.create(...)`.

- [ ] **Step 5: Import settings** in `backend/maps/api.py` if not already present — add near the top:
```python
from django.conf import settings
```

- [ ] **Step 6: Run — expect PASS** + whole suite green: `uv run pytest`

- [ ] **Step 7: Checks + commit:** ruff/format/mypy clean.

```bash
git add maps/api.py maps/tests/test_sandbox.py
git commit -m "feat(a4a): sandbox creation caps (session/IP/global) + session-IP stamping"
```

---

## Task 5: `editable` on the read API

**Files:**
- Modify: `backend/maps/schemas.py` (`NoteOut`, `AppendOut`)
- Modify: `backend/maps/api.py` (`list_notes`)
- Test: `backend/maps/tests/test_sandbox.py`

- [ ] **Step 1: Write failing tests** — append to `backend/maps/tests/test_sandbox.py`:

```python
def _list(client, world, preview_as):
    r = client.get(f"/api/v1/maps/{world['map'].id}/notes?preview_as={preview_as.id}")
    assert r.status_code == 200
    return r.json()


def test_editable_true_only_for_own_session_in_sandbox(world, settings):
    settings.SANDBOX_MODE = True
    owner = Client()
    _create_note(owner, world, world["alice"], title="mine")
    mine = next(n for n in _list(owner, world, world["alice"]) if n["title"] == "mine")
    assert mine["editable"] is True
    # the seed note is never editable
    seed = next(n for n in _list(owner, world, world["alice"]) if n["title"] == "Seed")
    assert seed["editable"] is False
    # a fresh session sees my note as not editable
    assert next(n for n in _list(Client(), world, world["alice"]) if n["title"] == "mine")["editable"] is False


def test_editable_matches_author_when_not_sandbox(world, settings):
    settings.SANDBOX_MODE = False
    note_id = _create_note(Client(), world, world["alice"])
    seen = next(n for n in _list(Client(), world, world["alice"]) if n["id"] == note_id)
    assert seen["editable"] is True  # author == preview_as
    seen_other = next(n for n in _list(Client(), world, world["bob"]) if n["id"] == note_id)
    assert seen_other["editable"] is False
```

- [ ] **Step 2: Run — expect FAIL** (no `editable` field): `uv run pytest maps/tests/test_sandbox.py -k editable -v`

- [ ] **Step 3: Add the field** to `backend/maps/schemas.py` — add `editable: bool` to both `AppendOut` (after `sections`) and `NoteOut` (after `appends`):

```python
class AppendOut(Schema):
    id: UUID
    author_id: UUID
    author_name: str
    title: str
    sections: list[SectionOut]
    editable: bool
```
```python
class NoteOut(Schema):
    id: UUID
    author_id: UUID
    title: str
    lng: float | None
    lat: float | None
    sections: list[SectionOut]
    appends: list[AppendOut] = []
    editable: bool
```

- [ ] **Step 4: Populate it** in `list_notes` (`backend/maps/api.py`). When building each `AppendOut(...)` add `editable=is_editable(request, ap, preview_as),` and when building each `NoteOut(...)` add `editable=is_editable(request, note, preview_as),`.

- [ ] **Step 5: Run — expect PASS** + whole suite. If any existing read test constructs/asserts on the full `NoteOut`/`AppendOut` shape and now fails for a missing `editable`, it's an over-strict assertion in the test — update that test to expect the new field: `uv run pytest`

- [ ] **Step 6: Checks + commit:** ruff/format/mypy clean.

```bash
git add maps/schemas.py maps/api.py maps/tests/test_sandbox.py
git commit -m "feat(a4a): server-computed editable flag on the note read API"
```

---

## Task 6: `/api/v1/health` endpoint

**Files:**
- Modify: `backend/maps/api.py` (add `health`)
- Test: `backend/maps/tests/test_health.py`

- [ ] **Step 1: Write the failing test** — `backend/maps/tests/test_health.py`:

```python
from django.test import Client


def test_health_reports_ok(db):
    r = Client().get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body and "git_sha" in body
```

- [ ] **Step 2: Run — expect FAIL** (404): `uv run pytest maps/tests/test_health.py -v`

- [ ] **Step 3: Add the endpoint** to `backend/maps/api.py` (put it just after `router = Router()`). It does a light DB check so the Render healthcheck fails loudly if the DB is unreachable:

```python
@router.get("/health")
def health(request):
    from django.db import connection

    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as exc:  # pragma: no cover - exercised only when the DB is down
        raise HttpError(503, "database unavailable") from exc
    return {"status": "ok", "version": settings.API_VERSION, "git_sha": settings.GIT_SHA}
```

(`settings` was imported in Task 4. The `render.yaml` `healthCheckPath` is already `/api/v1/health`.)

- [ ] **Step 4: Run — expect PASS:** `uv run pytest maps/tests/test_health.py -v`

- [ ] **Step 5: Checks + commit:** ruff/format/mypy clean.

```bash
git add maps/api.py maps/tests/test_health.py
git commit -m "feat(a4a): /api/v1/health endpoint (db check + version/git_sha)"
```

---

## Task 7: `reap_ephemeral` management command (7-day TTL)

**Files:**
- Create: `backend/maps/management/commands/reap_ephemeral.py`
- Test: `backend/maps/tests/test_reaper.py`

- [ ] **Step 1: Write the failing test** — `backend/maps/tests/test_reaper.py`:

```python
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from maps.models import Note


def test_reaper_deletes_old_ephemeral_keeps_seed_and_recent(world):
    old = Note.objects.create(tenant=world["tenant"], map=world["map"], author=world["alice"],
        title="old", is_seed=False)
    # backdate created_at past the 7-day TTL (created_at is auto_now_add, so update directly)
    Note.all_objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=8))
    recent = Note.objects.create(tenant=world["tenant"], map=world["map"], author=world["alice"],
        title="recent", is_seed=False)

    call_command("reap_ephemeral")

    assert not Note.all_objects.filter(id=old.id).exists()       # old ephemeral → gone
    assert Note.all_objects.filter(id=recent.id).exists()        # recent ephemeral → kept
    assert Note.all_objects.filter(id=world["seed"].id).exists() # seed → always kept
```

- [ ] **Step 2: Run — expect FAIL** (unknown command): `uv run pytest maps/tests/test_reaper.py -v`

- [ ] **Step 3: Create** `backend/maps/management/commands/reap_ephemeral.py`:

```python
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from maps.models import Note

TTL_DAYS = 7


class Command(BaseCommand):
    help = "Hard-delete ephemeral sandbox content older than the TTL (seed is never touched)."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=TTL_DAYS)
        # all_objects so already-soft-deleted rows are purged too; .delete() is a hard
        # SQL DELETE and cascades to child appends (Note.parent on_delete=CASCADE).
        qs = Note.all_objects.filter(is_seed=False, created_at__lt=cutoff)
        count = qs.count()
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Reaped {count} ephemeral notes/appends older than {TTL_DAYS}d."))
```

- [ ] **Step 4: Run — expect PASS:** `uv run pytest maps/tests/test_reaper.py -v`

- [ ] **Step 5: Checks + commit:** ruff/format/mypy clean.

```bash
git add maps/management/commands/reap_ephemeral.py maps/tests/test_reaper.py
git commit -m "feat(a4a): reap_ephemeral command — 7-day TTL for sandbox content"
```

---

## Task 8: Frontend — `editable` wiring, cross-origin cookies, sandbox banner, limit errors

**Files:**
- Modify: `frontend/src/api/types.ts` (`editable` on `NoteOut`/`AppendOut`)
- Modify: `frontend/src/api/maps.ts` (`credentials: "include"` in both fetch wrappers)
- Modify: `frontend/src/components/NotePanel.tsx` (append edit affordance from `editable`)
- Modify: `frontend/src/MapScreen.tsx` (note `canEdit` from `editable`; 429 surfacing; banner)
- Modify: `frontend/src/locales/en.json` (+ `editor.sandboxLimit`, `sandbox.banner`)
- Test: `frontend/src/MapScreen.test.tsx` (or the existing NotePanel/MapScreen tests)

- [ ] **Step 1: Add `editable` to the types** in `frontend/src/api/types.ts` — add `editable: boolean;` to both the `AppendOut` and `NoteOut` interfaces.

- [ ] **Step 2: Send cookies cross-origin** in `frontend/src/api/maps.ts` — add `credentials: "include"` to the `fetch` options in BOTH `getJson` (`fetch(url, { credentials: "include" })`) and `sendJson` (add `credentials: "include"` alongside `method`/`headers`/`body`).

- [ ] **Step 3: Surface the server's limit message** — in `frontend/src/api/maps.ts`, make `sendJson` attach the server's `detail` to the thrown error so callers can show it. Replace the error throw in `sendJson` with:

```ts
  if (!res.ok) {
    let detail = `${method} ${url} → ${res.status}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch { /* non-JSON error body */ }
    throw makeApiError(res.status, detail);
  }
```

- [ ] **Step 4: Drive append edit affordance from `editable`** — in `frontend/src/components/NotePanel.tsx`, change the ownership line from `const own = previewAs != null && ap.author_id === previewAs;` to:

```tsx
          const own = ap.editable;
```

- [ ] **Step 5: Drive note edit affordance from `editable` + surface 429 + render banner** in `frontend/src/MapScreen.tsx`:
  - Find where the `NotePanel` `canEdit` prop is computed for the selected note (currently based on `author_id === previewAs`) and change it to use the note's `editable` field (`canEdit={selectedNote.editable}` — match the actual variable name in the file).
  - In the `handleSave`/create/append error handling, where `409` is already mapped to `editor.conflict`, add: if `(e as ApiError).status === 429`, show `e.message` (the server detail from Step 3) — or fall back to `t("editor.sandboxLimit")` if the message is empty.
  - Render a sandbox banner at the top of the screen, gated on the build-time flag so it only shows on the deploy:

```tsx
{import.meta.env.VITE_SANDBOX === "true" && (
  <div className="sandbox-banner">{t("sandbox.banner")}</div>
)}
```

- [ ] **Step 6: Add the i18n strings** to `frontend/src/locales/en.json`:

```json
  "editor.sandboxLimit": "Sandbox limit reached — content here is pruned after 7 days.",
  "sandbox.banner": "Sandbox — anyone can edit, and content is removed 7 days after it's added."
```

- [ ] **Step 7: Update tests** — wherever the frontend test fixtures build a `NoteOut`/`AppendOut` (e.g. `MapScreen.test.tsx`, `NotePanel.test.tsx`), add `editable: false` (or `true` where the test exercises the edit affordance) so types compile and the existing edit-affordance tests still target the right notes. Add one test asserting the append edit button shows only when `editable: true`:

```tsx
// in the NotePanel test file
it("shows append edit controls only when the append is editable", () => {
  // render NotePanel with one append editable:true and one editable:false,
  // assert the ✎ append button count matches the editable ones
});
```
(Flesh this out to match the file's existing render helper + queries.)

- [ ] **Step 8: Verify:** `npm run test -- --run` (all green), `npm run lint` (clean, `--max-warnings 0`), `npx tsc -b`, `npm run build`.

- [ ] **Step 9: Commit:**

```bash
git add frontend/src frontend/src/locales/en.json
git commit -m "feat(a4a): frontend editable wiring, cross-origin cookies, sandbox banner + limit errors"
```

---

## Task 9: Deploy config — `render.yaml` cron + sandbox env + cross-site cookie/CORS settings

**Files:**
- Modify: `render.yaml` (sandbox env vars, cron service, `VITE_SANDBOX`)
- Modify: `backend/annotated_maps/settings.py` (cross-site cookies + CORS credentials in prod)

- [ ] **Step 1: Cross-site cookie + CORS-credentials settings.** In `backend/annotated_maps/settings.py`, add `CORS_ALLOW_CREDENTIALS = True` next to the existing `CORS_ALLOWED_ORIGINS` line, and add cross-site session-cookie settings inside the existing `if not DEBUG:` block (so local dev is unaffected):

```python
CORS_ALLOW_CREDENTIALS = True
```
and within `if not DEBUG:`:
```python
    # The web app and API are served from different Render domains, so the session
    # cookie must be sent on cross-site XHR. SameSite=None requires Secure (set above).
    SESSION_COOKIE_SAMESITE = "None"
    CSRF_COOKIE_SAMESITE = "None"
```

- [ ] **Step 2: Add sandbox env + the reaper cron service to `render.yaml`.** Under the API web service's `envVars`, add:

```yaml
      - key: SANDBOX_MODE
        value: "true"
      - key: CORS_ALLOWED_ORIGINS
        sync: false   # the web service's public URL, e.g. https://annotated-maps-web.onrender.com
```
Under the static web service's `envVars`, add:

```yaml
      - key: VITE_SANDBOX
        value: "true"
```
And add a third service (a daily cron running the reaper on the same image):

```yaml
  - type: cron
    name: annotated-maps-reaper
    runtime: docker
    dockerfilePath: ./backend/Dockerfile
    schedule: "17 4 * * *"   # daily 04:17 UTC
    dockerCommand: uv run python manage.py reap_ephemeral
    envVars:
      - key: DATABASE_URL
        sync: false
      - key: DJANGO_SECRET_KEY
        sync: false
      - key: SANDBOX_MODE
        value: "true"
```

- [ ] **Step 3: Verify config sanity** (no automated runtime test — this is deploy config): from `backend/`, confirm settings still import and the suite is green with the new settings (DEBUG=True locally, so the cross-site block is dormant):

```bash
uv run python -c "import annotated_maps.settings"
uv run pytest -q
```
Also confirm `render.yaml` is valid YAML: `uv run python -c "import yaml,sys; yaml.safe_load(open('../render.yaml'))"`.

- [ ] **Step 4: Commit:**

```bash
git add ../render.yaml annotated_maps/settings.py
git commit -m "feat(a4a): render.yaml sandbox env + reaper cron; cross-site cookie/CORS settings"
```

---

## Task 10: Deploy & smoke-test (manual runbook — user-executed)

This task is **not** agent-executable: it needs the user's Render + Neon accounts. The agent writes the runbook; the user runs it and reports back. Produce `docs/DEPLOY.md` and stop for the user.

**Files:**
- Create: `docs/DEPLOY.md`

- [ ] **Step 1: Write `docs/DEPLOY.md`** containing the exact, ordered runbook:
  1. **Neon:** create a project; in the SQL editor run `CREATE EXTENSION IF NOT EXISTS postgis;`; copy the pooled connection string (the `DATABASE_URL`).
  2. **Render:** New → Blueprint → point at the repo; it reads `render.yaml` (API web + static web + reaper cron).
  3. **Env vars to set** (the `sync:false` ones): on the API service — `DATABASE_URL` (Neon), `DJANGO_ALLOWED_HOSTS` (the API service hostname), `CORS_ALLOWED_ORIGINS` (the web service URL), `MOD_TOKEN` (a long random string — used in A4b); on the reaper cron — `DATABASE_URL`, `DJANGO_SECRET_KEY` (copy the API's generated value); on the static web — `VITE_API_BASE` (the API service URL, e.g. `https://annotated-maps-api.onrender.com/api/v1`).
  4. **First deploy:** the API `preDeployCommand` runs `migrate`. After it's live, seed once via the Render shell on the API service: `uv run python manage.py seed_demo`.
  5. **Smoke test** (record results): `GET /api/v1/health` → `{"status":"ok",…}`; open the web URL → the Boston note renders; flip "Viewing as" → sections appear/disappear; create a note as a persona → it appears, and is editable by you but not after opening an incognito window; the sandbox banner shows.
  6. **Cron check:** confirm the `annotated-maps-reaper` cron is registered (daily).
  7. Note the Render free-tier caveat (web services spin down when idle — first request after idle is slow) and the Render Cron plan note (if cron isn't available on the chosen plan, schedule an external ping to a `reap_ephemeral` trigger or run it manually; see spec).

- [ ] **Step 2: Commit the runbook:**

```bash
git add docs/DEPLOY.md
git commit -m "docs(a4a): deploy runbook for the public sandbox (Neon + Render)"
```

- [ ] **Step 3: STOP — hand off to the user** to execute `docs/DEPLOY.md` and report smoke-test results before this PR is considered done. The agent does not have deploy credentials.

---

## Definition of Done (A4a)

- [ ] `SANDBOX_MODE` gates all new behavior; the pre-existing suite stays green unmodified.
- [ ] Sandbox: seed is read-only; a session may edit/delete only its own ephemeral content; the three creation caps (per-session, per-IP/hour, global) return 429; ephemeral rows are stamped with session/IP.
- [ ] `editable` is server-computed on the read API and drives the frontend edit affordances; cross-origin cookies sent.
- [ ] `/api/v1/health` returns ok + version/git_sha; `reap_ephemeral` deletes >7-day ephemeral content (keeps seed + recent).
- [ ] Backend `uv run pytest` green; ruff/format/mypy + `makemigrations --check` clean. Frontend `test`/`lint`/`build` green.
- [ ] `render.yaml` has the sandbox env + reaper cron; cross-site cookie/CORS settings in place; `docs/DEPLOY.md` written.
- [ ] **Live deploy smoke-tested by the user** (Task 10).

## Out of scope (this PR)

The moderation page + endpoints (A4b); real auth (A5); region notes (A2); revision history; RLS.
