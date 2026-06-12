# Annotated Maps

A multi-tenant, permissioned map-annotation platform. Teams can create and share annotated map layers with fine-grained access control. The Django/PostGIS backend exposes a JSON API; a Vite/TypeScript frontend renders interactive maps. See `docs/superpowers/specs/` for design documents and `docs/architecture/production-lenses.md` for the architectural backlog.

## Local development

### Backend

```bash
# 1. Start the database (PostGIS)
cd backend && docker compose up -d db

# 2. Configure environment
cp .env.example .env   # edit as needed

# 3. Install dependencies and run
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Health check: http://localhost:8000/api/v1/health

#### macOS GDAL note

On macOS, if `manage.py` fails with **"Could not find the GDAL library"** (Homebrew ships a GDAL version newer than Django's auto-probe range), set `GDAL_LIBRARY_PATH` in `backend/.env`:

```
GDAL_LIBRARY_PATH=/usr/local/lib/libgdal.dylib
# or, using Homebrew's prefix:
# GDAL_LIBRARY_PATH=$(brew --prefix gdal)/lib/libgdal.dylib
```

The `.env.example` already has this line commented out. This is not needed on Linux, CI, or Docker.

### Frontend

```bash
cd frontend && npm install && npm run dev
```

Dev server: http://localhost:5173 — the Vite dev server proxies `/api` to the
Django backend on :8000, so run the backend alongside it.

To see the Boston demo (the section-visibility "Viewing as" map), seed it once:

```bash
cd backend && uv run python manage.py seed_demo
```

Then open the dev server and switch personas (Guest / A Friend / Run-club Member /
Reputable Local / owner) to watch the markers and note panel re-filter live.

## Tests

```bash
# Backend
cd backend && uv run pytest

# Frontend
cd frontend && npm run test -- --run
```

## Deploy

`render.yaml` is a [Render Blueprint](https://render.com/docs/blueprint-spec) that provisions:

- **annotated-maps-api** — Docker service running the Django/Gunicorn backend
- **annotated-maps-web** — static site serving the compiled Vite SPA

Render creates automatic per-PR preview environments. The database is external (Neon Postgres + PostGIS); set the `DATABASE_URL` environment variable per environment in the Render dashboard. `DJANGO_ALLOWED_HOSTS` must also be set per environment to include the service's public hostname.
