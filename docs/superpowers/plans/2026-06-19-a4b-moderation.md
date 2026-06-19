# A4b — Moderation Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A token-gated moderation tool — two endpoints (`GET /mod/recent`, `POST /mod/delete`) plus an unlisted React `/moderate` page — so the owner can review and prune sandbox content (individual rows, or everything from a session/IP).

**Architecture:** A new `maps/mod_api.py` router holds both endpoints, guarded by a constant-time `X-Mod-Token` check against a `MOD_TOKEN` env setting (empty token → all requests 401, so it's inert until configured). Deletes are logged to the existing append-only `AuditEvent`. The frontend adds a self-contained `ModerationScreen` reached by a `window.location.pathname === "/moderate"` check in `App.tsx` (the app has no router; this avoids adding one). The mod endpoints use the token header, NOT session cookies.

**Tech Stack:** Django-Ninja + the existing `AuditEvent` model; React + TS (no new deps).

**Spec:** `docs/superpowers/specs/2026-06-18-a4-public-sandbox-demo-design.md` (the "Moderation page (PR A4b)" section). This is **PR A4b**, building on the merged A4a sandbox.

**Conventions:** backend from `backend/`, `uv run …`; DB up via `docker compose up -d db` + wait for `pg_isready`. Run the FULL backend gate after each backend task: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run python manage.py makemigrations --check --dry-run`. Frontend from `frontend/`.

The `world` fixture (in `backend/maps/tests/conftest.py`) provides `world["tenant"]`, `world["map"]`, `world["alice"]`, `world["bob"]`, `world["seed"]` (a seed note `is_seed=True`). `Note` has `is_seed`/`session_key`/`created_ip`. `AuditEvent` (in `core/models.py`) has `action`, `target_type`, `target_id`, `actor_id`, `metadata` (JSON), `tenant`.

---

## Task 1: `MOD_TOKEN` auth + `GET /mod/recent`

**Files:**
- Modify: `backend/annotated_maps/settings.py` (add `MOD_TOKEN`)
- Modify: `render.yaml` (add `MOD_TOKEN` env to the API service)
- Create: `backend/maps/mod_api.py` (router + token guard + recent endpoint)
- Modify: `backend/maps/schemas.py` (add `ModItemOut`)
- Modify: `backend/annotated_maps/api.py` (mount the mod router)
- Test: `backend/maps/tests/test_mod_api.py`

- [ ] **Step 1: Add the setting** to `backend/annotated_maps/settings.py`, near the other env reads (e.g. after the `SANDBOX_MODE` line):
```python
# Moderation API shared secret. Empty by default → the mod endpoints reject every
# request (401), so they are inert until MOD_TOKEN is set on the deploy.
MOD_TOKEN = env("MOD_TOKEN", default="")
```

- [ ] **Step 2: Add `MOD_TOKEN` to `render.yaml`** under the API web service's `envVars` (a secret set at deploy time):
```yaml
      - key: MOD_TOKEN
        sync: false   # a long random string; enables the /moderate tooling
```

- [ ] **Step 3: Write failing tests** — `backend/maps/tests/test_mod_api.py`:
```python
import json

from django.test import Client

from maps.models import Note


def _ephemeral(world, author, title="v", session="full-session-key-123", ip="203.0.113.5", parent=None):
    return Note.objects.create(
        tenant=world["tenant"], map=world["map"], author=author, title=title,
        is_seed=False, session_key=session, created_ip=ip, parent=parent,
    )


def test_mod_recent_requires_token(world, settings):
    settings.MOD_TOKEN = "secret"
    assert Client().get("/api/v1/mod/recent").status_code == 401
    assert Client().get("/api/v1/mod/recent", HTTP_X_MOD_TOKEN="wrong").status_code == 401


def test_mod_recent_lists_ephemeral_not_seed(world, settings):
    settings.MOD_TOKEN = "secret"
    _ephemeral(world, world["alice"], title="visible one")
    r = Client().get("/api/v1/mod/recent", HTTP_X_MOD_TOKEN="secret")
    assert r.status_code == 200
    items = r.json()
    titles = [i["title"] for i in items]
    assert "visible one" in titles
    assert "Seed" not in titles  # the seed note is never listed
    item = next(i for i in items if i["title"] == "visible one")
    assert item["kind"] == "note"
    assert item["session_key"] == "full-session-key-123"  # FULL key (UI truncates it)
    assert item["created_ip"] == "203.0.113.5"
    assert item["author_name"] == "Alice"


def test_mod_recent_empty_token_setting_rejects_all(world, settings):
    settings.MOD_TOKEN = ""  # unset → inert
    assert Client().get("/api/v1/mod/recent", HTTP_X_MOD_TOKEN="").status_code == 401
```

- [ ] **Step 4: Run — expect FAIL** (404/no router): `uv run pytest maps/tests/test_mod_api.py -v`

- [ ] **Step 5: Add `ModItemOut`** to `backend/maps/schemas.py` (add `from datetime import datetime` at the top if absent):
```python
class ModItemOut(Schema):
    id: UUID
    kind: str  # "note" | "append"
    title: str
    snippet: str
    author_name: str
    session_key: str  # FULL key (token-gated, so safe to expose to the moderator); UI truncates
    created_ip: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    map_name: str
```

- [ ] **Step 6: Create** `backend/maps/mod_api.py`:
```python
"""Token-gated moderation API for the public sandbox. Guarded by a shared MOD_TOKEN
secret (X-Mod-Token header); inert when MOD_TOKEN is unset. Exposes session/IP — these
fields are NEVER returned by the public note API, only here."""

from __future__ import annotations

import hmac

from django.conf import settings
from ninja import Router
from ninja.errors import HttpError

from maps.models import Note
from maps.schemas import ModItemOut

router = Router()


def require_mod_token(request) -> None:
    """Reject unless the request carries the correct X-Mod-Token (constant-time).
    An empty MOD_TOKEN setting rejects everything, so the tooling is off by default."""
    expected = settings.MOD_TOKEN
    provided = request.headers.get("X-Mod-Token", "")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HttpError(401, "Unauthorized.")


@router.get("/mod/recent", response=list[ModItemOut])
def mod_recent(request, limit: int = 50):
    require_mod_token(request)
    limit = max(1, min(limit, 200))
    notes = (
        Note.objects.filter(is_seed=False)
        .select_related("author", "map")
        .prefetch_related("sections")
        .order_by("-updated_at")[:limit]
    )
    out: list[ModItemOut] = []
    for n in notes:
        first = next(iter(n.sections.all()), None)
        out.append(
            ModItemOut(
                id=n.id,
                kind="append" if n.parent_id else "note",
                title=n.title,
                snippet=(first.content[:80] if first else ""),
                author_name=n.author.display_name,
                session_key=n.session_key,  # full key — group-delete matches on it; UI truncates
                created_ip=n.created_ip,
                created_at=n.created_at,
                updated_at=n.updated_at,
                version=n.version,
                map_name=n.map.name,
            )
        )
    return out
```

- [ ] **Step 7: Mount the router** in `backend/annotated_maps/api.py`:
```python
from ninja import NinjaAPI

from core.api import router as core_router
from maps.api import router as maps_router
from maps.mod_api import router as mod_router

api = NinjaAPI(version="1.0.0", title="Annotated Maps API")
api.add_router("/", core_router)
api.add_router("/", maps_router)
api.add_router("/", mod_router)
```

- [ ] **Step 8: Run — expect PASS** + FULL gate:
```
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run python manage.py makemigrations --check --dry-run
```

- [ ] **Step 9: Commit:**
```bash
git add backend/annotated_maps/settings.py backend/annotated_maps/api.py backend/maps/mod_api.py backend/maps/schemas.py backend/maps/tests/test_mod_api.py render.yaml
git commit -m "feat(a4b): MOD_TOKEN auth + GET /mod/recent (list ephemeral sandbox content)"
```

---

## Task 2: `POST /mod/delete` + audit logging

**Files:**
- Modify: `backend/maps/schemas.py` (`ModDeleteIn`, `ModDeleteOut`)
- Modify: `backend/maps/mod_api.py` (delete endpoint)
- Test: `backend/maps/tests/test_mod_api.py`

- [ ] **Step 1: Write failing tests** — append to `backend/maps/tests/test_mod_api.py`:
```python
from core.models import AuditEvent


def test_mod_delete_by_ids(world, settings):
    settings.MOD_TOKEN = "secret"
    n = _ephemeral(world, world["alice"], title="kill me")
    r = Client().post(
        "/api/v1/mod/delete", data=json.dumps({"ids": [str(n.id)]}),
        content_type="application/json", HTTP_X_MOD_TOKEN="secret",
    )
    assert r.status_code == 200 and r.json()["deleted"] == 1
    assert not Note.all_objects.filter(id=n.id).exists()


def test_mod_delete_by_session_then_ip(world, settings):
    settings.MOD_TOKEN = "secret"
    _ephemeral(world, world["alice"], session="abuser", ip="9.9.9.9")
    _ephemeral(world, world["bob"], session="abuser", ip="9.9.9.9")
    r = Client().post(
        "/api/v1/mod/delete", data=json.dumps({"session_key": "abuser"}),
        content_type="application/json", HTTP_X_MOD_TOKEN="secret",
    )
    assert r.json()["deleted"] == 2


def test_mod_delete_never_touches_seed(world, settings):
    settings.MOD_TOKEN = "secret"
    seed_id = str(world["seed"].id)
    r = Client().post(
        "/api/v1/mod/delete", data=json.dumps({"ids": [seed_id]}),
        content_type="application/json", HTTP_X_MOD_TOKEN="secret",
    )
    assert r.json()["deleted"] == 0
    assert Note.all_objects.filter(id=seed_id).exists()  # seed survives


def test_mod_delete_requires_token_and_exactly_one_criterion(world, settings):
    settings.MOD_TOKEN = "secret"
    assert Client().post("/api/v1/mod/delete", data="{}", content_type="application/json").status_code == 401
    # token ok but zero/two criteria → 422 validation error
    r = Client().post(
        "/api/v1/mod/delete", data=json.dumps({"session_key": "a", "created_ip": "1.1.1.1"}),
        content_type="application/json", HTTP_X_MOD_TOKEN="secret",
    )
    assert r.status_code == 422


def test_mod_delete_writes_audit_event(world, settings):
    settings.MOD_TOKEN = "secret"
    n = _ephemeral(world, world["alice"])
    Client().post(
        "/api/v1/mod/delete", data=json.dumps({"ids": [str(n.id)]}),
        content_type="application/json", HTTP_X_MOD_TOKEN="secret",
    )
    ev = AuditEvent.objects.filter(action="mod.delete").latest("created_at")
    assert ev.metadata["deleted"] == 1
```

- [ ] **Step 2: Run — expect FAIL:** `uv run pytest maps/tests/test_mod_api.py -k delete -v`

- [ ] **Step 3: Add the schemas** to `backend/maps/schemas.py` (uses `model_validator`, already imported in this file per A1.3; add it if absent: `from pydantic import model_validator`):
```python
class ModDeleteIn(Schema):
    ids: list[UUID] | None = None
    session_key: str | None = None
    created_ip: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        provided = [self.ids is not None, bool(self.session_key), bool(self.created_ip)]
        if sum(provided) != 1:
            raise ValueError("Provide exactly one of: ids, session_key, created_ip.")
        return self


class ModDeleteOut(Schema):
    deleted: int
```

- [ ] **Step 4: Add the delete endpoint** to `backend/maps/mod_api.py` (extend the imports: `from core.models import AuditEvent` and add `ModDeleteIn, ModDeleteOut` to the `maps.schemas` import):
```python
@router.post("/mod/delete", response=ModDeleteOut)
def mod_delete(request, payload: ModDeleteIn):
    require_mod_token(request)
    # all_objects + is_seed=False: hard-delete ephemeral rows only; the seed is never
    # touched. Cascades to child appends + sections (on_delete=CASCADE).
    qs = Note.all_objects.filter(is_seed=False)
    if payload.ids is not None:
        qs = qs.filter(id__in=payload.ids)
        criterion = {"ids": [str(i) for i in payload.ids]}
    elif payload.session_key:
        qs = qs.filter(session_key=payload.session_key)
        criterion = {"session_key": payload.session_key}
    else:
        qs = qs.filter(created_ip=payload.created_ip)
        criterion = {"created_ip": payload.created_ip}
    count = qs.count()
    qs.delete()
    AuditEvent.objects.create(
        action="mod.delete", target_type="note", metadata={**criterion, "deleted": count}
    )
    return ModDeleteOut(deleted=count)
```

- [ ] **Step 5: Run — expect PASS** + FULL gate (pytest + ruff + format + mypy + makemigrations).

- [ ] **Step 6: Commit:**
```bash
git add backend/maps/mod_api.py backend/maps/schemas.py backend/maps/tests/test_mod_api.py
git commit -m "feat(a4b): POST /mod/delete (by ids/session/ip, never seed) + AuditEvent log"
```

---

## Task 3: Frontend `/moderate` page

**Files:**
- Create: `frontend/src/api/mod.ts` (token-header client)
- Create: `frontend/src/ModerationScreen.tsx`
- Modify: `frontend/src/App.tsx` (route `/moderate` → ModerationScreen)
- Modify: `frontend/src/locales/en.json` (mod strings)
- Modify: `frontend/src/index.css` (minimal table styling)
- Test: `frontend/src/ModerationScreen.test.tsx`

- [ ] **Step 1: Create the API client** `frontend/src/api/mod.ts`:
```ts
import { API_BASE } from "./apiBase";

export interface ModItem {
  id: string;
  kind: string;
  title: string;
  snippet: string;
  author_name: string;
  session_key: string;
  created_ip: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  map_name: string;
}

export interface ModDeleteBody {
  ids?: string[];
  session_key?: string;
  created_ip?: string;
}

async function modFetch<T>(path: string, token: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "X-Mod-Token": token,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const modRecent = (token: string, limit = 50) =>
  modFetch<ModItem[]>(`/mod/recent?limit=${limit}`, token);
export const modDelete = (token: string, body: ModDeleteBody) =>
  modFetch<{ deleted: number }>(`/mod/delete`, token, "POST", body);
```

- [ ] **Step 2: Create** `frontend/src/ModerationScreen.tsx`. Behavior: if no token yet, show a token prompt; once a token is entered (kept in `sessionStorage` + state), load `/mod/recent` and render a table with a per-row checkbox, a "Delete selected" button, and per-row "del session" / "del IP" group buttons; every delete confirms via `window.confirm` and reloads the list on success; a `401` clears the token and shows an auth error.
```tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { modRecent, modDelete, type ModItem, type ModDeleteBody } from "./api/mod";

export function ModerationScreen() {
  const { t } = useTranslation();
  const [token, setToken] = useState<string>(() => sessionStorage.getItem("modToken") ?? "");
  const [entry, setEntry] = useState("");
  const [items, setItems] = useState<ModItem[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (tok: string) => {
    try {
      setItems(await modRecent(tok));
      setError(null);
    } catch (e) {
      if (String(e).includes("401")) {
        setToken("");
        sessionStorage.removeItem("modToken");
        setError(t("mod.badToken"));
      } else {
        setError(t("mod.loadFailed"));
      }
    }
  }, [t]);

  useEffect(() => {
    if (token) load(token);
  }, [token, load]);

  const run = async (body: ModDeleteBody, confirmMsg: string) => {
    if (!window.confirm(confirmMsg)) return;
    try {
      await modDelete(token, body);
      setChecked(new Set());
      await load(token);
    } catch {
      setError(t("mod.deleteFailed"));
    }
  };

  if (!token) {
    return (
      <main className="mod-screen">
        <h1>{t("mod.title")}</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sessionStorage.setItem("modToken", entry);
            setToken(entry);
          }}
        >
          <input
            type="password"
            aria-label={t("mod.tokenLabel")}
            placeholder={t("mod.tokenLabel")}
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
          />
          <button type="submit">{t("mod.unlock")}</button>
        </form>
        {error && <p className="mod-error">{error}</p>}
      </main>
    );
  }

  return (
    <main className="mod-screen">
      <h1>{t("mod.title")}</h1>
      {error && <p className="mod-error">{error}</p>}
      <button
        disabled={checked.size === 0}
        onClick={() => run({ ids: [...checked] }, t("mod.confirmSelected", { count: checked.size }))}
      >
        {t("mod.deleteSelected", { count: checked.size })}
      </button>
      <table className="mod-table">
        <thead>
          <tr>
            <th></th>
            <th>{t("mod.kind")}</th>
            <th>{t("mod.title")}</th>
            <th>{t("mod.author")}</th>
            <th>{t("mod.session")}</th>
            <th>{t("mod.ip")}</th>
            <th>{t("mod.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.id}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`select ${it.id}`}
                  checked={checked.has(it.id)}
                  onChange={(e) => {
                    const next = new Set(checked);
                    if (e.target.checked) next.add(it.id);
                    else next.delete(it.id);
                    setChecked(next);
                  }}
                />
              </td>
              <td>{it.kind}</td>
              <td>{it.title || it.snippet}</td>
              <td>{it.author_name}</td>
              <td title={it.session_key}>{it.session_key.slice(0, 8)}</td>
              <td>{it.created_ip}</td>
              <td>
                <button onClick={() => run({ session_key: it.session_key }, t("mod.confirmSession"))}>
                  {t("mod.delSession")}
                </button>
                {it.created_ip && (
                  <button onClick={() => run({ created_ip: it.created_ip! }, t("mod.confirmIp"))}>
                    {t("mod.delIp")}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
```
NOTE: group-delete matches on the FULL `session_key`. Task 1's `ModItemOut.session_key` already returns the full key (it's token-gated), so the "del session" button sends `it.session_key` (full) while the session cell displays only `it.session_key.slice(0, 8)` (with the full value in a `title=` tooltip). No backend change needed here.

- [ ] **Step 3: Route `/moderate`** in `frontend/src/App.tsx`:
```tsx
import "./i18n";
import { MapScreen } from "./MapScreen";
import { ModerationScreen } from "./ModerationScreen";

export default function App() {
  if (typeof window !== "undefined" && window.location.pathname === "/moderate") {
    return <ModerationScreen />;
  }
  return <MapScreen />;
}
```

- [ ] **Step 4: Add i18n strings** to `frontend/src/locales/en.json`:
```json
  "mod.title": "Sandbox moderation",
  "mod.tokenLabel": "Moderation token",
  "mod.unlock": "Unlock",
  "mod.badToken": "Invalid token.",
  "mod.loadFailed": "Couldn’t load recent content.",
  "mod.deleteFailed": "Delete failed — try again.",
  "mod.kind": "Kind",
  "mod.author": "Author",
  "mod.session": "Session",
  "mod.ip": "IP",
  "mod.actions": "Actions",
  "mod.deleteSelected": "Delete selected ({{count}})",
  "mod.confirmSelected": "Delete {{count}} selected item(s)?",
  "mod.delSession": "Del session",
  "mod.delIp": "Del IP",
  "mod.confirmSession": "Delete ALL content from this session?",
  "mod.confirmIp": "Delete ALL content from this IP?"
```

- [ ] **Step 5: Add minimal CSS** for `.mod-screen` / `.mod-table` / `.mod-error` to `frontend/src/index.css` (match the file's existing style; a simple padded table with bordered cells and a red `.mod-error`). Keep it minimal.

- [ ] **Step 6: Write the test** `frontend/src/ModerationScreen.test.tsx` (mock `./api/mod`):
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { ModerationScreen } from "./ModerationScreen";
import * as modApi from "./api/mod";

vi.mock("./api/mod");

const item: modApi.ModItem = {
  id: "n1", kind: "note", title: "spam", snippet: "buy now", author_name: "Alice",
  session_key: "sess-abcdef12", created_ip: "9.9.9.9", created_at: "", updated_at: "",
  version: 1, map_name: "Demo",
};

beforeEach(() => {
  sessionStorage.clear();
  vi.resetAllMocks();
  vi.mocked(modApi.modRecent).mockResolvedValue([item]);
  vi.mocked(modApi.modDelete).mockResolvedValue({ deleted: 1 });
});

test("prompts for a token, then lists recent content", async () => {
  render(<ModerationScreen />);
  await userEvent.type(screen.getByLabelText(/moderation token/i), "secret");
  await userEvent.click(screen.getByRole("button", { name: /unlock/i }));
  expect(await screen.findByText("spam")).toBeInTheDocument();
  expect(modApi.modRecent).toHaveBeenCalledWith("secret");
});

test("deletes selected rows by id", async () => {
  sessionStorage.setItem("modToken", "secret");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ModerationScreen />);
  await userEvent.click(await screen.findByLabelText(/select n1/i));
  await userEvent.click(screen.getByRole("button", { name: /delete selected/i }));
  await waitFor(() => expect(modApi.modDelete).toHaveBeenCalledWith("secret", { ids: ["n1"] }));
});
```

- [ ] **Step 7: Verify:** `npm run test -- --run`, `npm run lint` (--max-warnings 0), `npx tsc -b`, `npm run build` — all green.

- [ ] **Step 8: Commit:**
```bash
git add frontend/src
git commit -m "feat(a4b): /moderate page — token-gated recent list + bulk/group delete"
```

---

## Definition of Done (A4b)

- [ ] `GET /mod/recent` + `POST /mod/delete` are token-gated (401 without/with bad token; inert when `MOD_TOKEN` unset); recent lists ephemeral content (never seed) with session/IP; delete works by ids/session/ip, NEVER deletes seed, and logs an `AuditEvent`.
- [ ] `ModItemOut` returns the full `session_key` (token-gated) so group-delete matches; the UI displays it truncated.
- [ ] Backend gate green (pytest + ruff + format + mypy + makemigrations). Frontend test/lint/tsc/build green.
- [ ] `/moderate` route renders the tool; token held in sessionStorage, sent as `X-Mod-Token`, never bundled.
- [ ] `render.yaml` has `MOD_TOKEN` (sync:false). No migration (reuses `AuditEvent`).

## Out of scope

Real admin auth / roles (the token is a coarse shared secret, sufficient for a personal demo); pagination/search in the mod UI (top-N by recency suffices); editing content from the mod page (delete-only). Real auth remains A5.
