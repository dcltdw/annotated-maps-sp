# Foundation (Phase 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a deployed, CI-green walking skeleton (frontend → API → PostGIS database) with the cross-cutting foundation seams in place, so feature phases A1–A5 build on solid ground.

**Architecture:** API-first monorepo. A Django + Django Ninja backend exposes a versioned `/api/v1` with an OpenAPI schema; a Vite + React + TypeScript PWA consumes it. PostgreSQL + PostGIS is the database. Cross-cutting concerns — tenant-scoped base models, structured logging with request/tenant/user correlation, an append-only audit log, security headers, expand-contract migrations — are established before any feature code. App servers are stateless (DB-backed sessions, no local files) so the system scales out.

**Tech Stack:** Python 3.12, Django 5.x, django-ninja, psycopg 3, PostGIS, django-environ, structlog, pytest + pytest-django, ruff, mypy + django-stubs, uv (Python tooling). Node 20, Vite, React 18, TypeScript, vite-plugin-pwa, react-i18next, Vitest + Testing Library, ESLint + eslint-plugin-jsx-a11y, openapi-typescript. GitHub Actions (CI). Docker + render.yaml (deploy). Spec: `docs/superpowers/specs/2026-06-08-annotated-maps-design.md` (§15 + `docs/architecture/production-lenses.md` define the foundation seams).

---

## File Structure

```
backend/
  pyproject.toml                # uv project, deps, ruff/mypy/pytest config
  manage.py
  .env.example
  docker-compose.yml            # local Postgres+PostGIS
  Dockerfile
  annotated_maps/               # Django project
    __init__.py
    settings.py                 # env-driven, 12-factor, stateless
    urls.py                     # mounts the Ninja API at /api/v1
    api.py                      # NinjaAPI instance (version 1.0.0)
    wsgi.py / asgi.py
  core/                         # cross-cutting app (no feature models yet)
    __init__.py
    apps.py
    models.py                   # BaseModel, TenantScopedModel, Tenant, AuditEvent
    managers.py                 # SoftDeleteManager
    logging.py                  # structlog configuration
    middleware.py               # ObservabilityMiddleware, SecurityHeadersMiddleware
    audit.py                    # record_event() helper
    api.py                      # health router
    migrations/
    tests/
      test_postgis.py
      test_models.py
      test_health.py
      test_observability.py
      test_security_headers.py
      test_audit.py
frontend/
  package.json
  tsconfig.json
  vite.config.ts                # + PWA plugin
  index.html
  eslint.config.js              # flat config + jsx-a11y
  src/
    main.tsx
    App.tsx
    i18n.ts
    locales/en.json
    api/health.ts
    App.test.tsx
.github/
  workflows/ci.yml
  pull_request_template.md
  scripts/check_pr_body.py      # enforces PR template sections
docs/adr/
  0000-template.md
  0001-record-architecture-decisions.md
  0002-tech-stack.md
  0003-postgis-for-geometry.md
  0004-pwa-now-native-later.md
  0005-rls-tenant-isolation-deferred.md
  0006-expand-contract-migrations.md
render.yaml                     # deploy blueprint + preview envs
README.md                       # run + deploy instructions
```

Each task below produces a self-contained, committable change. Run all backend commands from `backend/` and all frontend commands from `frontend/` unless stated otherwise.

---

## Task 1: Backend project scaffold

**Files:**
- Create: `backend/pyproject.toml`, `backend/manage.py`, `backend/annotated_maps/{__init__,settings,urls,wsgi,asgi}.py`, `backend/core/{__init__,apps}.py`

- [ ] **Step 1: Initialize the uv project and add dependencies**

Run from repo root:
```bash
mkdir -p backend && cd backend
uv init --python 3.12 --no-readme
uv add "django>=5.0,<5.2" "django-ninja>=1.3" "psycopg[binary]>=3.2" django-environ structlog "django-cors-headers>=4.4"
uv add --dev pytest pytest-django ruff mypy django-stubs "django-stubs-ext"
```

- [ ] **Step 2: Create the Django project and core app**

```bash
uv run django-admin startproject annotated_maps .
uv run python manage.py startapp core
```

- [ ] **Step 3: Append tool config to `backend/pyproject.toml`**

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "DJ"]

[tool.mypy]
plugins = ["mypy_django_plugin.main"]
ignore_missing_imports = true
check_untyped_defs = true
[tool.django-stubs]
django_settings_module = "annotated_maps.settings"

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "annotated_maps.settings"
python_files = ["test_*.py"]
addopts = "-q"
```

- [ ] **Step 4: Replace `INSTALLED_APPS` block in `backend/annotated_maps/settings.py`**

```python
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "corsheaders",
    "core",
]
```
(We deliberately omit `admin`/`auth` UI apps for now — auth is a deferred slice. `sessions` is added in Task 2.)

- [ ] **Step 5: Verify the project checks out**

Run: `uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add backend/
git commit -m "feat(foundation): scaffold Django + Ninja backend project"
```

---

## Task 2: Local PostGIS + stateless DB-driven settings

**Files:**
- Create: `backend/docker-compose.yml`, `backend/.env.example`
- Modify: `backend/annotated_maps/settings.py`

- [ ] **Step 1: Create `backend/docker-compose.yml`**

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_DB: annotated_maps
      POSTGRES_USER: annotated_maps
      POSTGRES_PASSWORD: localdev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

- [ ] **Step 2: Create `backend/.env.example`**

```bash
DJANGO_SECRET_KEY=dev-insecure-change-me
DJANGO_DEBUG=true
DATABASE_URL=postgis://annotated_maps:localdev@localhost:5432/annotated_maps
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:5173
GIT_SHA=dev
```

Also append to the repo-root `.gitignore`:

```gitignore
# Python / Django
backend/.env
__pycache__/
*.pyc
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/
# Node
frontend/node_modules/
frontend/dist/
```

- [ ] **Step 3: Rewrite the config section of `backend/annotated_maps/settings.py`**

Replace the auto-generated `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASES`, `MIDDLEWARE`, and session settings with:

```python
import environ

env = environ.Env(DJANGO_DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost"])

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

# Stateless app tier: sessions live in the DB, not in-process.
INSTALLED_APPS += ["django.contrib.sessions"]
SESSION_ENGINE = "django.contrib.sessions.backends.db"

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
]
```

- [ ] **Step 4: Start the database and verify the connection**

```bash
docker compose up -d db
cp .env.example .env
uv run python manage.py check --database default
```
Expected: no database errors.

- [ ] **Step 5: Commit**

```bash
git add backend/docker-compose.yml backend/.env.example backend/annotated_maps/settings.py
git commit -m "feat(foundation): PostGIS database + stateless env-driven settings"
```

---

## Task 3: Enable the PostGIS extension via migration

**Files:**
- Create: `backend/core/migrations/0001_enable_postgis.py`, `backend/core/tests/__init__.py`, `backend/core/tests/test_postgis.py`

- [ ] **Step 1: Write the failing test** (`backend/core/tests/test_postgis.py`)

```python
import pytest
from django.db import connection

@pytest.mark.django_db
def test_postgis_extension_is_available():
    with connection.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'postgis';")
        assert cur.fetchone() is not None, "PostGIS extension is not installed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest core/tests/test_postgis.py -v`
Expected: FAIL — the extension does not exist yet.

- [ ] **Step 3: Create the migration** (`backend/core/migrations/0001_enable_postgis.py`)

```python
from django.contrib.postgres.operations import CreateExtension
from django.db import migrations

class Migration(migrations.Migration):
    initial = True
    operations = [CreateExtension("postgis")]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest core/tests/test_postgis.py -v`
Expected: PASS (pytest-django applies migrations to the test database).

- [ ] **Step 5: Commit**

```bash
git add backend/core/migrations/0001_enable_postgis.py backend/core/tests/
git commit -m "feat(foundation): enable PostGIS extension via migration"
```

---

## Task 4: Tenant seam + base models (soft-delete, version, timestamps)

**Files:**
- Create: `backend/core/managers.py`, `backend/core/tests/test_models.py`
- Modify: `backend/core/models.py`
- Create: `backend/core/migrations/0002_base_models.py` (generated)

- [ ] **Step 1: Write the failing test** (`backend/core/tests/test_models.py`)

```python
import pytest
from core.models import Tenant

@pytest.mark.django_db
def test_tenant_has_uuid_pk_and_timestamps():
    t = Tenant.objects.create(name="Boston Demo", slug="boston-demo")
    assert str(t.id)  # UUID renders
    assert t.created_at is not None and t.updated_at is not None

@pytest.mark.django_db
def test_version_increments_on_save():
    t = Tenant.objects.create(name="A", slug="a")
    assert t.version == 1
    t.name = "B"
    t.save()
    assert t.version == 2

@pytest.mark.django_db
def test_soft_delete_hides_from_default_manager():
    t = Tenant.objects.create(name="A", slug="a")
    t.soft_delete()
    assert Tenant.objects.filter(pk=t.pk).count() == 0
    assert Tenant.all_objects.filter(pk=t.pk).count() == 1
    assert t.deleted_at is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest core/tests/test_models.py -v`
Expected: FAIL — `Tenant` not defined.

- [ ] **Step 3: Create `backend/core/managers.py`**

```python
from django.db import models

class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)
```

- [ ] **Step 4: Write `backend/core/models.py`**

```python
import uuid
from django.db import models
from django.utils import timezone
from core.managers import SoftDeleteManager

class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.version = (self.version or 0) + 1
        super().save(*args, **kwargs)

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "version", "updated_at"])

class Tenant(BaseModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)

    def __str__(self) -> str:
        return self.name

class TenantScopedModel(BaseModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True
```

- [ ] **Step 5: Generate and apply the migration**

```bash
uv run python manage.py makemigrations core --name base_models
uv run pytest core/tests/test_models.py -v
```
Expected: migration `0002_base_models.py` created; tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/core/
git commit -m "feat(foundation): Tenant seam + base models (soft-delete, version, timestamps)"
```

---

## Task 5: Versioned `/api/v1` + health endpoint

**Files:**
- Create: `backend/annotated_maps/api.py`, `backend/core/api.py`, `backend/core/tests/test_health.py`
- Modify: `backend/annotated_maps/urls.py`, `backend/annotated_maps/settings.py`

- [ ] **Step 1: Write the failing test** (`backend/core/tests/test_health.py`)

```python
import pytest
from django.test import Client

@pytest.mark.django_db
def test_health_returns_ok_with_version():
    resp = Client().get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body and "git_sha" in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest core/tests/test_health.py -v`
Expected: FAIL — 404, route not mounted.

- [ ] **Step 3: Create the health router** (`backend/core/api.py`)

```python
from ninja import Router
from django.conf import settings

router = Router()

@router.get("/health")
def health(request):
    return {"status": "ok", "version": settings.API_VERSION, "git_sha": settings.GIT_SHA}
```

- [ ] **Step 4: Create the API instance** (`backend/annotated_maps/api.py`)

```python
from ninja import NinjaAPI
from core.api import router as core_router

api = NinjaAPI(version="1.0.0", title="Annotated Maps API")
api.add_router("/", core_router)
```

- [ ] **Step 5: Mount at `/api/v1`** — replace `backend/annotated_maps/urls.py`

```python
from django.urls import path
from annotated_maps.api import api

urlpatterns = [path("api/v1/", api.urls)]
```

- [ ] **Step 6: Add version settings** — append to `backend/annotated_maps/settings.py`

```python
API_VERSION = "1.0.0"
GIT_SHA = env("GIT_SHA", default="dev")
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest core/tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/annotated_maps/ backend/core/api.py backend/core/tests/test_health.py
git commit -m "feat(foundation): versioned /api/v1 with health endpoint"
```

---

## Task 6: Observability — structured logs with request/tenant/user correlation

**Files:**
- Create: `backend/core/logging.py`, `backend/core/middleware.py`, `backend/core/tests/test_observability.py`
- Modify: `backend/annotated_maps/settings.py`

- [ ] **Step 1: Write the failing test** (`backend/core/tests/test_observability.py`)

```python
import pytest
from django.test import Client

@pytest.mark.django_db
def test_response_carries_request_id_header():
    resp = Client().get("/api/v1/health")
    assert resp.headers.get("X-Request-ID")

@pytest.mark.django_db
def test_incoming_request_id_is_echoed():
    rid = "test-correlation-123"
    resp = Client().get("/api/v1/health", headers={"X-Request-ID": rid})
    assert resp.headers["X-Request-ID"] == rid
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest core/tests/test_observability.py -v`
Expected: FAIL — no `X-Request-ID` header.

- [ ] **Step 3: Create `backend/core/logging.py`**

```python
import logging
import structlog

def configure_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=logging.INFO)
```

- [ ] **Step 4: Create `backend/core/middleware.py`**

```python
import uuid
import structlog

class ObservabilityMiddleware:
    """Binds request/tenant/user IDs into the structlog contextvars for every log line."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            tenant_id=getattr(request, "tenant_id", None),
            user_id=getattr(request, "user_id", None),
        )
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response
```

- [ ] **Step 5: Wire it up** — in `backend/annotated_maps/settings.py`, call logging config and add the middleware

```python
from core.logging import configure_logging
configure_logging()

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "core.middleware.ObservabilityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest core/tests/test_observability.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/core/logging.py backend/core/middleware.py backend/core/tests/test_observability.py backend/annotated_maps/settings.py
git commit -m "feat(foundation): structured logging with request/tenant/user correlation"
```

---

## Task 7: Security headers

**Files:**
- Modify: `backend/core/middleware.py`, `backend/annotated_maps/settings.py`
- Create: `backend/core/tests/test_security_headers.py`

- [ ] **Step 1: Write the failing test** (`backend/core/tests/test_security_headers.py`)

```python
import pytest
from django.test import Client

@pytest.mark.django_db
def test_security_headers_present():
    resp = Client().get("/api/v1/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in resp.headers["Content-Security-Policy"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest core/tests/test_security_headers.py -v`
Expected: FAIL — headers absent.

- [ ] **Step 3: Add `SecurityHeadersMiddleware` to `backend/core/middleware.py`**

```python
class SecurityHeadersMiddleware:
    """Baseline security headers. CSP is locked down; loosen per-route when the SPA needs it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response
```

- [ ] **Step 4: Register it + production transport settings** — in `backend/annotated_maps/settings.py`

Add `"core.middleware.SecurityHeadersMiddleware"` to `MIDDLEWARE` (right after `ObservabilityMiddleware`), then append:

```python
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest core/tests/test_security_headers.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/core/middleware.py backend/annotated_maps/settings.py backend/core/tests/test_security_headers.py
git commit -m "feat(foundation): baseline security headers + prod transport hardening"
```

---

## Task 8: Audit-log seam

**Files:**
- Modify: `backend/core/models.py`
- Create: `backend/core/audit.py`, `backend/core/tests/test_audit.py`, `backend/core/migrations/0003_auditevent.py` (generated)

- [ ] **Step 1: Write the failing test** (`backend/core/tests/test_audit.py`)

```python
import pytest
from core.models import Tenant, AuditEvent
from core.audit import record_event

@pytest.mark.django_db
def test_record_event_persists_an_audit_row():
    tenant = Tenant.objects.create(name="A", slug="a")
    record_event("tenant.created", tenant=tenant, actor_id=None, target=tenant, note="seed")
    e = AuditEvent.all_objects.get()
    assert e.action == "tenant.created"
    assert e.tenant_id == tenant.id
    assert e.target_type == "Tenant"
    assert str(e.target_id) == str(tenant.id)
    assert e.metadata == {"note": "seed"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest core/tests/test_audit.py -v`
Expected: FAIL — `AuditEvent` / `record_event` undefined.

- [ ] **Step 3: Add `AuditEvent` to `backend/core/models.py`**

```python
class AuditEvent(BaseModel):
    """Append-only log of security- and content-relevant events. Never updated or deleted."""

    tenant = models.ForeignKey(Tenant, null=True, on_delete=models.SET_NULL, related_name="+")
    actor_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
```

- [ ] **Step 4: Create `backend/core/audit.py`**

```python
from __future__ import annotations
from typing import Any
from core.models import AuditEvent, BaseModel, Tenant

def record_event(
    action: str,
    *,
    tenant: Tenant | None = None,
    actor_id: Any = None,
    target: BaseModel | None = None,
    **metadata: Any,
) -> AuditEvent:
    return AuditEvent.all_objects.create(
        action=action,
        tenant=tenant,
        actor_id=actor_id,
        target_type=type(target).__name__ if target else "",
        target_id=target.id if target else None,
        metadata=metadata,
    )
```

- [ ] **Step 5: Generate the migration and run the test**

```bash
uv run python manage.py makemigrations core --name auditevent
uv run pytest core/tests/test_audit.py -v
```
Expected: migration created; test PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/core/
git commit -m "feat(foundation): append-only audit-log seam"
```

---

## Task 9: Frontend PWA scaffold + health page + i18n + a11y

**Files:**
- Create: `frontend/` (Vite scaffold), `frontend/src/{App.tsx,api/health.ts,i18n.ts,locales/en.json,App.test.tsx}`, `frontend/.eslintrc.cjs`, `frontend/vite.config.ts`

- [ ] **Step 1: Scaffold the app and add dependencies**

Run from repo root:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install react-i18next i18next
npm install -D vite-plugin-pwa vitest @testing-library/react @testing-library/jest-dom jsdom openapi-typescript eslint @eslint/js typescript-eslint eslint-plugin-jsx-a11y
```

- [ ] **Step 2: Configure Vite + PWA + Vitest** (`frontend/vite.config.ts`)

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [react(), VitePWA({ registerType: "autoUpdate", manifest: { name: "Annotated Maps", short_name: "Maps", start_url: "/" } })],
  test: { environment: "jsdom", globals: true, setupFiles: "./src/setupTests.ts" },
});
```

- [ ] **Step 3: Add i18n scaffolding** (`frontend/src/locales/en.json` and `frontend/src/i18n.ts`)

`src/locales/en.json`:
```json
{ "health.title": "API status", "health.ok": "Connected", "health.error": "Unavailable" }
```

`src/i18n.ts`:
```ts
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";

i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});
export default i18n;
```

- [ ] **Step 4: Add the API helper** (`frontend/src/api/health.ts`)

```ts
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export async function fetchHealth(): Promise<{ status: string; version: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 5: Write the failing component test** (`frontend/src/App.test.tsx`)

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import App from "./App";

vi.mock("./api/health", () => ({ fetchHealth: () => Promise.resolve({ status: "ok", version: "1.0.0" }) }));

test("shows connected status once health resolves", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
});
```

Create `frontend/src/setupTests.ts`:
```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `npm run test -- --run` (after adding `"test": "vitest"` to `package.json` scripts)
Expected: FAIL — `App` does not render "Connected".

- [ ] **Step 7: Implement `frontend/src/App.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import "./i18n";
import { fetchHealth } from "./api/health";

export default function App() {
  const { t } = useTranslation();
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    fetchHealth().then(() => setOk(true)).catch(() => setOk(false));
  }, []);
  return (
    <main>
      <h1>{t("health.title")}</h1>
      <p role="status">{ok === null ? "…" : ok ? t("health.ok") : t("health.error")}</p>
    </main>
  );
}
```

- [ ] **Step 8: Add a11y lint config** (`frontend/eslint.config.js`, flat config)

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import jsxA11y from "eslint-plugin-jsx-a11y";

export default tseslint.config(
  { ignores: ["dist/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { files: ["src/**/*.{ts,tsx}"], plugins: { "jsx-a11y": jsxA11y }, rules: jsxA11y.configs.recommended.rules },
);
```

- [ ] **Step 9: Run the test + build to verify**

```bash
npm run test -- --run
npm run build
```
Expected: test PASS; build succeeds.

- [ ] **Step 10: Commit**

```bash
git add frontend/
git commit -m "feat(foundation): React PWA scaffold with health page, i18n, and a11y lint"
```

---

## Task 10: CI + PR provenance/docs/tests enforcement

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/pull_request_template.md`, `.github/scripts/check_pr_body.py`

- [ ] **Step 1: Create the PR template** (`.github/pull_request_template.md`)

```markdown
## Summary

## Files changed (created / modified / deleted)
<!-- CI appends the diff file list; summarize intent here -->

## Provenance
- Agent:
- Model / version:

## Reasoning & alternatives considered
<!-- Link any ADRs in docs/adr/ -->

## Testing
<!-- What tests were added/modified/deleted, and the result -->

## Risk & rollback
```

- [ ] **Step 2: Create the section-enforcement script** (`.github/scripts/check_pr_body.py`)

```python
import os
import sys

REQUIRED = ["## Summary", "## Provenance", "## Reasoning", "## Testing", "## Risk & rollback"]
body = os.environ.get("PR_BODY", "")
missing = [h for h in REQUIRED if h not in body]
# Reject empty-after-heading sections too.
empty = [h for h in REQUIRED if h in body and not body.split(h, 1)[1].strip().lstrip("#")[:1]]
if missing or empty:
    print(f"PR body missing sections: {missing}; empty sections: {empty}")
    sys.exit(1)
print("PR body OK")
```

- [ ] **Step 3: Create the CI workflow** (`.github/workflows/ci.yml`)

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      db:
        image: postgis/postgis:16-3.4
        env: { POSTGRES_DB: annotated_maps, POSTGRES_USER: annotated_maps, POSTGRES_PASSWORD: localdev }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U annotated_maps" --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      DATABASE_URL: postgis://annotated_maps:localdev@localhost:5432/annotated_maps
      DJANGO_SECRET_KEY: ci-insecure
      DJANGO_DEBUG: "false"
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run mypy .
      - run: uv run pytest

  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: npm ci
      - run: npx eslint src
      - run: npm run test -- --run
      - run: npm run build

  pr-rigor:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - env: { PR_BODY: ${{ github.event.pull_request.body }} }
        run: python .github/scripts/check_pr_body.py
```

- [ ] **Step 4: Verify the script locally**

```bash
PR_BODY="$(cat .github/pull_request_template.md)" python .github/scripts/check_pr_body.py
```
Expected: exits non-zero (template sections are empty) — confirming the check actually catches empty PRs. A real filled-in PR body passes.

- [ ] **Step 5: Commit**

```bash
git add .github/
git commit -m "ci(foundation): backend+frontend pipeline and PR rigor enforcement"
```

---

## Task 11: Deploy skeleton (Docker + render.yaml) + README

**Files:**
- Create: `backend/Dockerfile`, `render.yaml`, `README.md`
- Modify: `backend/pyproject.toml` (add `gunicorn`)

- [ ] **Step 1: Add the production server dependency**

Run from `backend/`: `uv add gunicorn`

- [ ] **Step 2: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends binutils libproj-dev gdal-bin && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./
ENV PORT=8000
CMD uv run gunicorn annotated_maps.wsgi --bind 0.0.0.0:$PORT
```

- [ ] **Step 3: Create `render.yaml` (blueprint + automatic preview environments)**

```yaml
previews:
  generation: automatic
services:
  - type: web
    name: annotated-maps-api
    runtime: docker
    dockerfilePath: ./backend/Dockerfile
    healthCheckPath: /api/v1/health
    envVars:
      - key: DATABASE_URL
        sync: false   # Neon connection string, set per-environment
      - key: DJANGO_SECRET_KEY
        generateValue: true
      - key: DJANGO_DEBUG
        value: "false"
      - key: GIT_SHA
        fromCommit: true
  - type: web
    name: annotated-maps-web
    runtime: static
    buildCommand: cd frontend && npm ci && npm run build
    staticPublishPath: ./frontend/dist
    envVars:
      - key: VITE_API_BASE
        sync: false
```

- [ ] **Step 4: Write `README.md`** (run + deploy instructions)

```markdown
# Annotated Maps

A multi-tenant, permissioned map-annotation app. See `docs/superpowers/specs/` for the design and `docs/architecture/production-lenses.md` for the architectural backlog.

## Local development
1. `cd backend && docker compose up -d db && cp .env.example .env`
2. `uv sync && uv run python manage.py migrate`
3. `uv run python manage.py runserver`  → http://localhost:8000/api/v1/health
4. `cd ../frontend && npm install && npm run dev`  → http://localhost:5173

## Tests
- Backend: `cd backend && uv run pytest`
- Frontend: `cd frontend && npm run test -- --run`

## Deploy
Render Blueprint (`render.yaml`) provisions the API (Docker) and static SPA, with automatic per-PR preview environments. The database is external (Neon Postgres + PostGIS); set `DATABASE_URL` per environment.
```

- [ ] **Step 5: Verify the image builds**

Run from repo root: `docker build -f backend/Dockerfile -t annotated-maps-api .`
Expected: image builds successfully.

- [ ] **Step 6: Commit**

```bash
git add backend/Dockerfile render.yaml README.md backend/pyproject.toml backend/uv.lock
git commit -m "feat(foundation): deploy skeleton (Docker + render.yaml) and README"
```

---

## Task 12: ADR log (record the decisions already made)

**Files:**
- Create: `docs/adr/0000-template.md`, `docs/adr/0001-record-architecture-decisions.md`, `docs/adr/0002-tech-stack.md`, `docs/adr/0003-postgis-for-geometry.md`, `docs/adr/0004-pwa-now-native-later.md`, `docs/adr/0005-rls-tenant-isolation-deferred.md`, `docs/adr/0006-expand-contract-migrations.md`

- [ ] **Step 1: Create the ADR template** (`docs/adr/0000-template.md`)

```markdown
# ADR-NNNN: <title>
- Status: <proposed | accepted | superseded by ADR-XXXX>
- Date: YYYY-MM-DD
## Context
## Decision
## Consequences
```

- [ ] **Step 2: Write ADR-0001** (`docs/adr/0001-record-architecture-decisions.md`)

```markdown
# ADR-0001: Record architecture decisions
- Status: accepted
- Date: 2026-06-09
## Context
We want the reasoning behind significant decisions to be durable and reviewable.
## Decision
We record each significant architectural decision as an ADR in `docs/adr/`. PRs link to the relevant ADR in their Reasoning section.
## Consequences
Decisions (and their deferrals) are legible to future contributors and reviewers.
```

- [ ] **Step 3: Write ADR-0002 (tech stack)** (`docs/adr/0002-tech-stack.md`)

```markdown
# ADR-0002: Tech stack — Django + Ninja backend, React PWA frontend
- Status: accepted
- Date: 2026-06-09
## Context
Solo build by a Python-strong developer; cheap hosting (~$7/mo); API-first for web + future native; self-implemented auth on vetted libraries.
## Decision
Django + Django Ninja (typed API + OpenAPI) on PostgreSQL; React + TypeScript PWA via Vite. See spec §3.
## Consequences
Maximizes time in Python; Django auth primitives back the self-implemented auth; one typed API serves all clients.
```

- [ ] **Step 4: Write ADR-0003, 0004, 0005**

`docs/adr/0003-postgis-for-geometry.md`:
```markdown
# ADR-0003: PostGIS for geometry, stored as GeoJSON/WKB
- Status: accepted
- Date: 2026-06-09
## Context
Regions, point-in-region membership, and spatial selection need real geometry queries; later interop wants standard formats.
## Decision
Enable PostGIS from the foundation; store geometry as PostGIS types serialized via GeoJSON/WKB.
## Consequences
Spatial queries and import/export are first-class; avoids a painful geometry migration on live data.
```

`docs/adr/0004-pwa-now-native-later.md`:
```markdown
# ADR-0004: Responsive PWA now, native client later
- Status: accepted
- Date: 2026-06-09
## Context
"Usable on web and mobile" with the cheapest hosting and one codebase; native is a showcase option later.
## Decision
Ship one responsive installable PWA over the API-first backend; defer a native client to its own slice.
## Consequences
Fastest path to a usable, cheap demo; the API boundary keeps a native client a clean future add.
```

`docs/adr/0005-rls-tenant-isolation-deferred.md`:
```markdown
# ADR-0005: Tenant isolation via RLS, enforced when auth lands
- Status: accepted
- Date: 2026-06-09
## Context
Multi-tenant data needs hard isolation, but Slice A uses a single seeded tenant and trivial auth.
## Decision
Thread `tenant_id` on every domain row from day one; enable Postgres Row-Level Security policies when real auth lands.
## Consequences
The column and access paths exist now; turning on RLS later hardens a rule that is already threaded rather than adding a column under fire.
```

`docs/adr/0006-expand-contract-migrations.md`:
```markdown
# ADR-0006: Expand-contract (backward-compatible) migrations
- Status: accepted
- Date: 2026-06-09
## Context
Once production data exists, destructive or blocking migrations cause downtime and risk data loss.
## Decision
Every schema change follows expand-contract: add new (nullable / with default) → backfill → switch reads/writes → contract (drop old) in a later release. No column drop or type change in the same deploy that begins using it.
## Consequences
Zero-downtime deploys are possible from day one; migrations stay reversible and safe under load.
```

- [ ] **Step 5: Commit**

```bash
git add docs/adr/
git commit -m "docs(foundation): ADR log for the foundational decisions"
```

---

## Foundation: Definition of Done

- [ ] `cd backend && uv run pytest` is green; `ruff` and `mypy` clean.
- [ ] `cd frontend && npm run test -- --run` is green; `eslint` clean; `npm run build` succeeds.
- [ ] `GET /api/v1/health` returns `{status: "ok", version, git_sha}` with an `X-Request-ID` header and the security headers.
- [ ] CI is green on a PR; the `pr-rigor` job rejects an empty PR body.
- [ ] `docker build -f backend/Dockerfile .` succeeds; `render.yaml` defines the API + static SPA + automatic preview envs.
- [ ] Foundation seams present: PostGIS enabled, `tenant_id` base model, soft-delete + version, correlation-context logging, audit-log helper, `/api/v1` versioning, security headers, i18n + a11y scaffolding, ADRs recorded.

## Out of scope (later phases)

Feature models (Map, Note, Section, Collection), the visibility engine, real/trivial auth, object storage + `EmailSender` interfaces (introduced when first used in A1/A5), OSM tile rendering + attribution (lands with the map in A1), and RLS policy enforcement (lands with auth).
