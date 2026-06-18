# Hardening Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four independent robustness/quality fixes — off the deprecated Ninja tuple-return, race-free version concurrency, react-hooks lint enabled (warnings-as-errors), and Playwright e2e retries — with no product-behavior change.

**Architecture:** Backend: replace `return code, body` with `Status(code, body)`; rewrite `update_note`/`update_append`'s read-check-write 409 guard as an atomic `UPDATE … WHERE version=expected`. Frontend: wire `eslint-plugin-react-hooks`'s flat preset + `--max-warnings 0`; add Playwright `retries`/`workers`.

**Tech Stack:** Django 5 + Django-Ninja + PostGIS, pytest; React + TS (Vite), ESLint flat config, Playwright.

**Spec:** `docs/superpowers/specs/2026-06-18-hardening-pass-design.md`. The 4 tasks are independent — order is by convenience, not dependency.

---

## Task 1 (backend): off the deprecated Ninja tuple-return

5 endpoints in `maps/api.py` return `(status, body)` tuples, which Ninja 1.6.2 deprecates ("Use Status(status_code, response) instead"). Switch to `Status`.

**Files:** Modify `backend/maps/api.py`, `backend/maps/tests/test_notes_api.py`.

- [ ] **Step 1: Failing test** — append to `maps/tests/test_notes_api.py` (add `import warnings` at the top if absent):
```python
def test_create_does_not_emit_the_tuple_return_deprecation(boston):
    payload = {"title": "x", "lng": -71.0, "lat": 42.0,
        "sections": [{"content": "c", "rule_type": "public"}]}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resp = Client().post(
            f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}",
            data=json.dumps(payload), content_type="application/json",
        )
    assert resp.status_code == 201
    assert not any("Returning tuple" in str(w.message) for w in caught)
```

- [ ] **Step 2: Run — expect FAIL** (the warning is present): `uv run pytest maps/tests/test_notes_api.py -k tuple_return_deprecation -v`

- [ ] **Step 3: Import `Status` + replace the 5 tuple-returns** in `maps/api.py`. Change the ninja import line `from ninja import Router` to:
```python
from ninja import Router, Status
```
Then replace each return (the `response={code: Schema}` decorators stay unchanged):
- `create_note`: `return 201, {"id": note.id}` → `return Status(201, {"id": note.id})`
- `delete_note`: `return 204, None` → `return Status(204, None)`
- `update_note`: `return 200, {"id": note.id, "version": note.version}` → `return Status(200, {"id": note.id, "version": note.version})`
- `create_append`: `return 201, {"id": append.id}` → `return Status(201, {"id": append.id})`
- `update_append`: `return 200, {"id": append.id, "version": append.version}` → `return Status(200, {"id": append.id, "version": append.version})`

- [ ] **Step 4: Run — expect PASS** (the new test + the whole suite — every status-code assertion still holds): `uv run pytest`. Confirm the run output no longer contains "Returning tuple ... deprecated" warnings.

- [ ] **Step 5: Checks + commit:** `uv run ruff check . && uv run ruff format --check . && uv run mypy .`
```bash
git add maps/api.py maps/tests/test_notes_api.py
git commit -m "refactor(hardening): use ninja Status() instead of the deprecated tuple return"
```

---

## Task 2 (backend): atomic version concurrency

`update_note` and `update_append` use read-check-write (`if version != payload.version: 409` then `save()`), which has a TOCTOU race. Replace with an atomic `UPDATE … WHERE version=expected`. **Behavior-preserving refactor** — the existing edit / 409-conflict / version-increment / author-403 tests are the safety net (run them green before and after).

**Files:** Modify `backend/maps/api.py`.

- [ ] **Step 1: Confirm the safety-net tests are green first:** `uv run pytest maps/tests/test_notes_api.py -k "edits_own or version_conflict or non_author_cannot_edit" -v` (these must pass before the change so we know the refactor preserves them).

- [ ] **Step 2: Add imports** to `maps/api.py`:
```python
from django.db.models import F
from django.utils import timezone
```

- [ ] **Step 3: Rewrite `update_note`** (`maps/api.py`) — the body inside the function becomes:
```python
@router.put("/notes/{note_id}", response={200: NoteUpdated})
def update_note(request, note_id: UUID, payload: NoteUpdateIn, preview_as: UUID | None = None):
    note = get_object_or_404(Note, id=note_id)
    if preview_as is None or note.author_id != preview_as:
        raise HttpError(403, "You can only edit your own notes.")
    with transaction.atomic():
        # Atomically claim the version: exactly one of two racing PUTs can match
        # WHERE version=expected; the loser updates 0 rows → 409. (.update() bypasses
        # BaseModel.save(), so bump version + updated_at explicitly.)
        claimed = Note.objects.filter(id=note.id, version=payload.version).update(
            version=F("version") + 1,
            updated_at=timezone.now(),
            title=payload.title,
            point=Point(payload.lng, payload.lat),
        )
        if not claimed:
            raise HttpError(409, "This note changed elsewhere — reload to edit.")
        note.sections.all().delete()  # hard replace (see git history for the rationale)
        for s in payload.sections:
            Section.objects.create(
                note=note, order=s.order, content=s.content, rule_type=s.rule_type,
                rule_params=s.rule_params, teaser=s.teaser, teaser_text=s.teaser_text,
            )
    note.refresh_from_db()  # in-memory note is stale after the raw UPDATE
    return Status(200, {"id": note.id, "version": note.version})
```

- [ ] **Step 4: Rewrite `update_append`** (`maps/api.py`) — same pattern, no `point`, keeping the existing `parent_id is None → 400` guard:
```python
@router.put("/appends/{append_id}", response={200: NoteUpdated})
def update_append(
    request, append_id: UUID, payload: AppendUpdateIn, preview_as: UUID | None = None
):
    append = get_object_or_404(Note, id=append_id)
    if preview_as is None or append.author_id != preview_as:
        raise HttpError(403, "You can only edit your own appends.")
    if append.parent_id is None:
        raise HttpError(400, "Not an append.")
    with transaction.atomic():
        claimed = Note.objects.filter(id=append.id, version=payload.version).update(
            version=F("version") + 1,
            updated_at=timezone.now(),
            title=payload.title,
        )
        if not claimed:
            raise HttpError(409, "This append changed elsewhere — reload to edit.")
        append.sections.all().delete()
        for s in payload.sections:
            Section.objects.create(
                note=append, order=s.order, content=s.content, rule_type=s.rule_type,
                rule_params=s.rule_params, teaser=s.teaser, teaser_text=s.teaser_text,
            )
    append.refresh_from_db()
    return Status(200, {"id": append.id, "version": append.version})
```
*(This depends on Task 1's `Status` import. If Task 1 isn't done first, use `return 200, {...}` here and let Task 1 convert it — but the recommended order is T1 then T2.)*

- [ ] **Step 5: Add a focused test** that the version is consumed (a second edit with the original version → 409) — append to `maps/tests/test_notes_api.py`:
```python
def test_two_edits_with_the_same_starting_version_second_conflicts(boston):
    note = _note_with_sections(boston)
    v0 = note.version
    body = {"title": "first", "lng": -71.0, "lat": 42.0, "version": v0,
        "sections": [{"order": 0, "content": "a", "rule_type": "public"}]}
    r1 = Client().put(f"/api/v1/notes/{note.id}?preview_as={boston['owner'].id}",
        data=json.dumps(body), content_type="application/json")
    assert r1.status_code == 200 and r1.json()["version"] == v0 + 1
    # a second edit still presenting v0 must conflict (the version was consumed)
    body["title"] = "second"
    r2 = Client().put(f"/api/v1/notes/{note.id}?preview_as={boston['owner'].id}",
        data=json.dumps(body), content_type="application/json")
    assert r2.status_code == 409
    note.refresh_from_db()
    assert note.title == "first"  # the conflicting second edit did not apply
```
(`_note_with_sections` already exists in the file.)

- [ ] **Step 6: Run — expect PASS** (whole suite — all edit/conflict tests + the new one): `uv run pytest`

- [ ] **Step 7: Checks + commit:** ruff/format/mypy + `makemigrations --check` clean (no model change).
```bash
git add maps/api.py maps/tests/test_notes_api.py
git commit -m "refactor(hardening): atomic version concurrency for note/append edit (race-free 409)"
```

---

## Task 3 (frontend): enable react-hooks lint (warnings-as-errors)

Wire `eslint-plugin-react-hooks` (v7.1.1, installed) into the flat config and make warnings fail, then resolve every finding.

**Files:** Modify `frontend/eslint.config.js`, `frontend/package.json`, plus whatever source files the rule flags.

- [ ] **Step 1: Wire the plugin** into `frontend/eslint.config.js`. Add the import at the top and the preset to the `tseslint.config(...)` array:
```js
import reactHooks from "eslint-plugin-react-hooks";
```
and add (after the `tseslint.configs.recommended` spread, before the jsx-a11y block):
```js
  reactHooks.configs["recommended-latest"],
```
*(v7's `recommended-latest` is the flat-config preset; it sets `react-hooks/rules-of-hooks` = error and `react-hooks/exhaustive-deps` = warn. If ESLint errors on the config shape, the alternative is an explicit block: `{ plugins: { "react-hooks": reactHooks }, rules: reactHooks.configs.recommended.rules }` — verify with `npx eslint src`.)*

- [ ] **Step 2: Make warnings fail** — in `frontend/package.json`, change the `lint` script:
```json
    "lint": "eslint . --max-warnings 0"
```

- [ ] **Step 3: Run the lint to surface findings:** `npm run lint`. Expect failures — at minimum `MapView.tsx`'s create-once map effect (`useEffect(() => { … }, [])` that reads `center`/`zoom`) will trip `exhaustive-deps`. Note every file:line the rule flags.

- [ ] **Step 4: Resolve every finding.**
  - **Genuine bugs** (a missing dep that would cause a stale value / stale closure): fix by adding the dep or restructuring (e.g. wrap a handler in `useCallback`, read a value from a ref).
  - **Deliberate cases** (an effect that intentionally runs once / omits a dep): add a **justified** disable on the line above, e.g. in `src/components/MapView.tsx` on the create-once effect:
```tsx
    // center/zoom only seed the initial view; the map is created once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
```
  Apply the same pattern to any other intentional effect the rule flags (e.g. the markers/draft effects if they're flagged). Do NOT blanket-disable the rule file-wide; disable per-line with a reason. The `rules-of-hooks` rule (error) should produce **no** findings in correct code — if it does, that's a real bug to fix, not disable.

- [ ] **Step 5: Run — expect PASS:** `npm run lint` (0 errors, 0 warnings), then `npm run test -- --run` (behavior unchanged — all green), `npx tsc -b`, `npm run build`.

- [ ] **Step 6: Commit:**
```bash
git add -A frontend/eslint.config.js frontend/package.json frontend/src
git commit -m "chore(hardening): enable react-hooks lint (rules-of-hooks + exhaustive-deps, --max-warnings 0)"
```

---

## Task 4 (frontend): Playwright e2e flake-resilience

Add retries + capped CI parallelism so the timing-sensitive marker-count tests don't hard-fail under contention.

**Files:** Modify `frontend/playwright.config.ts`.

- [ ] **Step 1: Add `retries` + `workers`** to `defineConfig` in `frontend/playwright.config.ts` (alongside the existing top-level keys):
```ts
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 2 : 1, // flaky marker-count assertions retry instead of hard-failing
  workers: process.env.CI ? "50%" : undefined, // cap CI parallelism to reduce contention
  use: {
    baseURL: "http://localhost:5174",
    launchOptions: { args: ["--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev -- --port 5174",
    url: "http://localhost:5174",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
```

- [ ] **Step 2: Run — expect PASS:** `npm run e2e` (all specs green; on a quiet machine it passes first try, and retries cover any flake). `npx eslint e2e` clean.

- [ ] **Step 3: Commit:**
```bash
git add frontend/playwright.config.ts
git commit -m "test(hardening): Playwright retries + capped CI workers for e2e flake-resilience"
```

---

## Definition of Done

- [ ] Backend: no Ninja tuple-return deprecation in the pytest output; `update_note`/`update_append` use the atomic `UPDATE … WHERE version=expected` (409 race-free). `uv run pytest` green; ruff/format/mypy + `makemigrations --check` clean.
- [ ] Frontend: react-hooks lint enabled; `npm run lint` clean with `--max-warnings 0` (every finding fixed or justified-disabled); `npm run test -- --run` green; `npm run build` succeeds.
- [ ] e2e: `npm run e2e` green with retries configured.
- [ ] No product-behavior change (same API contract, same UI).

## Out of scope

Revision history (a feature); CSRF + multi-tenant RLS (A5 auth slice); making the `e2e` job a required merge gate (a GitHub ruleset toggle done by the user). Real auth, deploy, rate limits (the A5 live-demo line).
