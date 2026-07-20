# CLAUDE.md

Guidance for working in this repo. See [README.md](README.md) for the
user-facing description and [ROADMAP.md](ROADMAP.md) for the
production-engineering roadmap.

## What this is

A multi-tenant, permissioned map-annotation platform: a Django/PostGIS backend
exposing a JSON API and a Vite/TypeScript frontend. Deployed on Render + Neon
(live demo: https://annotated-maps-web.onrender.com/).

## Collaboration

Universal collaboration rules — branch → PR → wait for approval, many small
single-purpose PRs, the `Co-Authored-By` model stamp on commits, secret-scan
before push, project-board flow, and verify-before-done — come from the
machine-global import in `~/.claude/CLAUDE.md`
(`@~/.claude/dcltdw/AGENTS.md`), so they are not duplicated here. Edits to that
shared file propagate automatically; this file only adds repo-specific deltas on
top.

### PR bodies (repo-specific — section headings only)

This repo's CI enforces its own PR-body headings (the `pr-rigor` check,
`.github/scripts/check_pr_body.py`), so a PR here MUST use these exact headings
instead of the heading list in `universal.md` § PR bodies — each with real
content, or CI fails:

`## Summary`, `## Provenance`, `## Reasoning`, `## Testing`, `## Risk & rollback`

Only the headings differ — `universal.md`'s PR-body intent still applies and
still propagates. Its fields map onto these sections:

- Files changed + Work breakdown → **Summary**
- Test expectations → **Testing**
- Operational impact (deploy / migration / reseed notes) → **Risk & rollback**
- Provenance (`Agent:` + `Model / version:`) → **Provenance**, unchanged
- design rationale / alternatives considered → **Reasoning**

Everything else in `universal.md` applies as written.

## Project board

- Board: https://github.com/users/dcltdw/projects/6 (`PVT_kwHOAAdfes4Bcevp`) — **public**.
- Status field `PVTSSF_lAHOAAdfes4BcevpzhXHOIs`:
  Todo `f75ad846`, In Progress `47fc9ee4`, Done `98236657`, Won't Do `fa5df384`

(`universal.md` § "Project board" now carries the **Done** vs **Won't Do**
convention and the refinement/triage terminology — this file just records the
option IDs above and the repo-specific note below.)

Board items are **real GitHub issues** (converted from draft issues on
2026-07-20). A PR that resolves one should use `Closes #N` so the merge
auto-closes the issue — the fix for the stale-ticket problem that draft issues
used to cause. Moving the board card to Done still needs the manual step below;
`Closes #N` closes the *issue*, and the board Status field is independent of
issue open/closed state.

Re-derive the IDs if they drift:

```sh
gh api graphql -f query='{ user(login:"dcltdw"){ projectV2(number:6){ id
  field(name:"Status"){ ... on ProjectV2SingleSelectField { id options { id name } } } } } }'
```

## After a PR merges

`universal.md` § "After a PR merges" carries the generic spine (pull, verify
`main` actually contains the change, move the board card, ask what went stale,
delete the branch — with the squash-merge caveats). Repo-specific additions:

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
