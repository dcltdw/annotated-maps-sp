# Hardening Pass — Design

- **Status:** approved (brainstorming) — 2026-06-18
- **Relationship:** standalone quality/robustness pass on the merged Annotated Maps codebase (foundation → A1.3c). No new product features. Picked over the live-demo (A5) path and A2 (region notes) as a low-risk consolidation; the user is not in a rush for the live demo.
- **Scope (4 items, all chosen in brainstorming):** wire up react-hooks lint; silence the Ninja tuple-return deprecation; Playwright e2e flake-resilience; atomic version concurrency.

## 1. react-hooks lint

`eslint-plugin-react-hooks` (v7.1.1) is installed but not in the flat config. Wire its **`recommended-latest`** flat preset into `frontend/eslint.config.js` (scoped to `src/**`), enabling `react-hooks/rules-of-hooks` (error) + `react-hooks/exhaustive-deps` (warn). Then run `eslint` and **resolve every finding**:
- Genuine bugs (stale closures, missing deps) → fixed.
- Deliberate cases (e.g. `MapView`'s create-once map effect with `[]` deps; any effect that intentionally omits a dep) → a **justified** `// eslint-disable-next-line react-hooks/exhaustive-deps` with a one-line reason (the rule is now enabled, so the directive is valid, not an unused-directive error).
- Add **`--max-warnings 0`** to the `lint` npm script so `exhaustive-deps` warnings can't silently accumulate (CI's `npm run lint` then fails on any unresolved warning).

The exact number of findings is unknown until the rule runs; the implementation addresses each. **Success:** `npm run lint` clean (0 errors, 0 warnings); no behavior change to the app (tests stay green).

## 2. Silence the Ninja tuple-return deprecation

5 endpoints in `backend/maps/api.py` return the deprecated `(status_code, body)` tuple (`create_note`, `delete_note`, `update_note`, `create_append`, `update_append`) — every test run prints `DeprecationWarning: Returning tuple (status_code, response) is deprecated. Use Status(status_code, response) instead.`

Fix: `from ninja import Status` (exported by ninja 1.6.2) and replace each `return <code>, <body>` with `return Status(<code>, <body>)`. The `response={<code>: Schema}` operation mappings are unchanged. **Success:** pytest output carries no "Returning tuple … deprecated" warnings; all status codes + bodies unchanged (the API contract is identical).

## 3. Playwright e2e flake-resilience

`frontend/playwright.config.ts` is `fullyParallel: true` with no retries. Under heavy local machine load the marker-count assertions (`toHaveCount`) on the create/delete tests flake (CI on a fresh runner is currently stable). Add, without weakening any assertion:
- **`retries: process.env.CI ? 2 : 1`** — Playwright auto-retries a flaky test; a test that passes on retry is reported as flaky, not failed.
- **`workers: process.env.CI ? "50%" : undefined`** — cap CI parallelism to reduce contention (local keeps the default).

These are the standard Playwright flake mitigations and touch only the config. **Success:** `npm run e2e` green; the marker-count tests no longer hard-fail under contention.

## 4. Atomic version concurrency

`update_note` and `update_append` (`backend/maps/api.py`) use **read-check-write**: `if note.version != payload.version: raise 409` then `note.save()`. Two concurrent PUTs with the same expected version can both pass the check before either saves (a TOCTOU race). Replace with an **atomic conditional UPDATE** that claims the version in one statement:

```python
# (author 403 check still runs first, on the loaded note)
with transaction.atomic():
    claimed = Note.objects.filter(id=note_id, version=payload.version).update(
        version=F("version") + 1,
        updated_at=timezone.now(),   # .update() bypasses auto_now / BaseModel.save()
        title=payload.title,
        point=...,                   # note only; update_append omits point
    )
    if not claimed:                  # 0 rows → stale version (or deleted) → conflict
        raise HttpError(409, "This note changed elsewhere — reload to edit.")
    note.refresh_from_db()
    note.sections.all().delete()
    for s in payload.sections: Section.objects.create(...)
```

`WHERE version=expected` lets exactly one of two racing requests claim the bump; the loser updates 0 rows → 409. `.update()` bypasses `BaseModel.save()`, so the version increment + `updated_at` are set explicitly. **Success:** the existing 409 / version-increment tests pass unchanged (externally identical), now race-free; the section-replace + author 403 + transactional rollback behavior is preserved.

## Testing

- **Backend:** `uv run pytest` green; ruff/format/mypy + `makemigrations --check` clean. The existing note/append edit tests (200 + version+1, 409 on stale, 403 author, section replace) exercise the rewritten concurrency path; the Ninja change is asserted by the unchanged status-code assertions across the suite. No new migration.
- **Frontend:** `npm run test -- --run` green; **`npm run lint` clean with `--max-warnings 0`** (the react-hooks gate); `npm run build` succeeds.
- **e2e:** `npm run e2e` green (with retries).

## Out of scope

Revision history (a deferred *feature*, not hardening — edits still hard-replace sections); CSRF + multi-tenant RLS (belong with the A5 auth slice); making the `e2e` CI job a **required merge gate** (a GitHub branch-protection ruleset toggle — provided to the user as a one-liner, not changed here without prompting). Real auth, deployment, rate limits (the A5 live-demo line).
