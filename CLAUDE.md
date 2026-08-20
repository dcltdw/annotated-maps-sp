# CLAUDE.md

Guidance for working in this repo. See [README.md](README.md) for the
user-facing description and [ROADMAP.md](ROADMAP.md) for the
production-engineering roadmap.

## What this is

A multi-tenant, permissioned map-annotation platform: a Django/PostGIS backend
exposing a JSON API and a Vite/TypeScript frontend. Deployed on Render + Neon
(live demo: https://annotated-maps-web.onrender.com/).

## PR bodies (repo-specific — section headings only)

This repo's CI enforces its own PR-body headings (the `pr-rigor` check,
`.github/scripts/check_pr_body.py`), so a PR here MUST use these exact
headings — each with real content, or CI fails:

`## Summary`, `## Provenance`, `## Reasoning`, `## Testing`, `## Risk & rollback`

These **override** the five sections in the `dcltdw:opening-a-pr` skill. Only
the headings differ; that skill's intent — and its `Agent:` / `Model / version:`
provenance fields — still applies.

## Project board

- Board: https://github.com/users/dcltdw/projects/6 (`PVT_kwHOAAdfes4Bcevp`) — **public**.
- Status field `PVTSSF_lAHOAAdfes4BcevpzhXHOIs`:
  Todo `f75ad846`, In Progress `47fc9ee4`, Done `98236657`, Won't Do `fa5df384`

Board items are **real GitHub issues** (converted from draft issues on
2026-07-20). Moving a card to Done stays a manual step: `Closes #N` closes the
*issue*, and the board Status field is independent of issue open/closed state.

Re-derive the IDs if they drift:

```sh
gh api graphql -f query='{ user(login:"dcltdw"){ projectV2(number:6){ id
  field(name:"Status"){ ... on ProjectV2SingleSelectField { id options { id name } } } } } }'
```

## After a PR merges

The `dcltdw:cleaning-up-after-pr-merge` skill carries the generic steps.
Repo-specific additions:

- Update the session ledger (`.superpowers/sdd/progress.md`) if mid-plan, and
  memory if the merge is milestone-level.
- If it touched infra: verify the live AWS state matches `main`.
- If it ends a demo cycle: confirm nothing billable is running (`aws eks
  list-clusters`, and the sweep at the end of `scripts/demo-down.sh`).

## Documentation accuracy (ADR-0011)

- Before any docs-touching PR: `make docs-checks` (links + registered facts —
  the same commands CI runs).
- Editing a number guarded by a `<!-- fact: ... -->` annotation? Update the
  prose AND the annotation together; CI enforces both.
- New load-bearing claim? Triage first — delete → soften → detie to a
  CI-tested source → register — in that order (see
  [ADR-0011](docs/adr/0011-documentation-accuracy-practice.md)).
- Never edit dated/historical docs (`<!-- doc-status: dated -->`) to match
  current code.
- After milestone-sized merges, run `/docs-fact-check` (the monthly reminder
  issue covers the calendar cadence).
- Escape hatch when legitimately blocked mid-restructure:
  `Docs-Checks-Override: <reason>` in the PR body — it defers, never erases.
