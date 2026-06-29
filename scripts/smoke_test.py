#!/usr/bin/env python3
"""
smoke_test.py — post-deploy verifier for Annotated Maps public sandbox.

Usage:
    python3 scripts/smoke_test.py https://annotated-maps-api.onrender.com/api/v1

Requires only Python stdlib (urllib, http.cookiejar, json, sys).
A single cookie jar is used for all requests so the session cookie
persists across the create and the subsequent ownership check.

Exit codes:
    0 — all checks passed
    1 — at least one check failed
    2 — bad invocation (missing args)
"""

import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def build_opener() -> urllib.request.OpenerDirector:
    """Build a urllib opener with a persistent cookie jar."""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


# Module-level opener — shared by all calls so the session cookie carries over.
_opener: urllib.request.OpenerDirector | None = None
_base: str = ""


def call(method: str, path: str, body: object = None) -> tuple[int, object]:
    """
    Make an HTTP request against the API and return (status_code, parsed_json).

    Non-2xx responses are caught from HTTPError so callers can still
    assert the exact status code rather than having an exception unwind.
    The body argument (if given) is JSON-encoded and sent with
    Content-Type: application/json.
    """
    url = f"{_base}{path}"
    data: bytes | None = None
    headers: dict[str, str] = {}

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        assert _opener is not None, "opener not initialised"
        with _opener.open(req) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        # HTTPError is raised for 4xx / 5xx — capture code + body.
        raw = exc.read()
        status = exc.code

    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = None

    return status, parsed


# ---------------------------------------------------------------------------
# Assertion helper
# ---------------------------------------------------------------------------

def _ok(step: int, msg: str) -> None:
    # ANSI green — terminals that don't support ANSI just see the escape chars,
    # which is acceptable for a diagnostic script.
    print(f"\033[32mOK\033[0m  step {step}: {msg}")


def _fail(step: int, msg: str) -> None:
    print(f"FAIL step {step}: {msg}", file=sys.stderr)
    sys.exit(1)


def _assert(condition: bool, step: int, msg: str) -> None:
    if not condition:
        _fail(step, msg)


# ---------------------------------------------------------------------------
# Smoke-test steps
# ---------------------------------------------------------------------------

def main() -> None:
    global _opener, _base

    if len(sys.argv) < 2:
        print(
            "usage: python3 scripts/smoke_test.py https://<api-host>/api/v1",
            file=sys.stderr,
        )
        sys.exit(2)

    _base = sys.argv[1].rstrip("/")
    _opener = build_opener()

    print(f"Smoke-testing {_base}\n")

    # ------------------------------------------------------------------
    # Step 1 — Health check
    # ------------------------------------------------------------------
    status, data = call("GET", "/health")
    _assert(status == 200, 1, f"expected HTTP 200, got {status}")
    _assert(isinstance(data, dict), 1, "expected JSON object from /health")
    _assert(data.get("status") == "ok", 1, f"status != 'ok': {data}")
    version = data.get("version", "(unknown)")
    git_sha = data.get("git_sha", "(unknown)")
    _ok(1, f"health OK — version={version}  git_sha={git_sha}")

    # ------------------------------------------------------------------
    # Step 2 — List maps; take the first map id
    # ------------------------------------------------------------------
    status, data = call("GET", "/maps")
    _assert(status == 200, 2, f"expected HTTP 200, got {status}")
    _assert(isinstance(data, list) and len(data) >= 1, 2, f"expected ≥1 map, got: {data}")
    map_id = data[0]["id"]
    map_name = data[0].get("name", "?")
    _ok(2, f"maps OK — first map id={map_id!r} name={map_name!r}")

    # ------------------------------------------------------------------
    # Step 3 — List viewers; take the first viewer id as our persona
    # ------------------------------------------------------------------
    status, data = call("GET", f"/maps/{map_id}/viewers")
    _assert(status == 200, 3, f"expected HTTP 200, got {status}")
    _assert(isinstance(data, list) and len(data) >= 1, 3, f"expected ≥1 viewer, got: {data}")
    persona = data[0]["id"]
    viewer_name = data[0].get("display_name", "?")
    _ok(3, f"viewers OK — persona id={persona!r} name={viewer_name!r}")

    # ------------------------------------------------------------------
    # Step 4 — List notes; confirm seed note is NOT editable
    # ------------------------------------------------------------------
    status, data = call("GET", f"/maps/{map_id}/notes?preview_as={persona}")
    _assert(status == 200, 4, f"expected HTTP 200, got {status}")
    _assert(isinstance(data, list) and len(data) >= 1, 4, f"expected ≥1 note, got: {data}")

    # Prefer the Castle Island seed note; fall back to the first note.
    seed_note = next(
        (n for n in data if "Castle Island" in (n.get("title") or "")),
        data[0],
    )
    _assert(
        seed_note.get("editable") is False,
        4,
        f"seed note should be read-only (editable=false), got: {seed_note}",
    )
    _ok(4, f"seed note read-only OK — title={seed_note.get('title')!r}  editable=false")

    # ------------------------------------------------------------------
    # Step 5 — Create a new note
    # ------------------------------------------------------------------
    payload = {
        "title": "smoke-test note",
        "lng": -71.05,
        "lat": 42.35,
        "sections": [
            {
                "order": 0,
                "content": "hello from smoke_test",
                "rule_type": "public",
            }
        ],
    }
    status, data = call("POST", f"/maps/{map_id}/notes?preview_as={persona}", body=payload)
    _assert(status == 201, 5, f"expected HTTP 201, got {status} — body: {data}")
    _assert(isinstance(data, dict) and "id" in data, 5, f"expected {{id: ...}}, got: {data}")
    new_note_id = data["id"]
    _ok(5, f"create note OK — new note id={new_note_id!r}")

    # ------------------------------------------------------------------
    # Step 6 — Re-list notes; confirm the new note is editable by this session
    # ------------------------------------------------------------------
    status, data = call("GET", f"/maps/{map_id}/notes?preview_as={persona}")
    _assert(status == 200, 6, f"expected HTTP 200, got {status}")
    _assert(isinstance(data, list), 6, "expected list of notes")

    created_note = next((n for n in data if n.get("id") == new_note_id), None)
    _assert(
        created_note is not None,
        6,
        f"newly created note id={new_note_id!r} not found in note list",
    )
    _assert(
        created_note.get("editable") is True,
        6,
        f"own note should be editable (editable=true), got: {created_note}",
    )
    _ok(6, f"session ownership OK — note id={new_note_id!r} editable=true")

    # ------------------------------------------------------------------
    # Step 7 — Clean up so the smoke test leaves no pin behind in the public
    # sandbox. The session owns the note it just created, so it may delete it.
    # ------------------------------------------------------------------
    status, _ = call("DELETE", f"/notes/{new_note_id}?preview_as={persona}")
    _assert(status == 204, 7, f"expected HTTP 204 deleting the smoke note, got {status}")
    _ok(7, f"cleanup OK — deleted smoke note id={new_note_id!r}")

    # ------------------------------------------------------------------
    # All done
    # ------------------------------------------------------------------
    print("\n\033[32mAll smoke-test checks passed.\033[0m")
    sys.exit(0)


if __name__ == "__main__":
    main()
