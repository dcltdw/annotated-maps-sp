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
(`@~/Github/dcltdw/claude/universal.md`), so they are not duplicated here. Edits
to `universal.md` propagate automatically; this file only adds repo-specific
deltas on top.

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

Two terminal states, matching the GitHub/Jira/Linear convention: **Done** (work
happened) and **Won't Do** (reviewed, deliberately closed without action —
always append a one-line reason to the body). Say *refinement* or *triage*,
never "grooming".

Items are currently **draft issues**, so no `Closes #N` and no auto-close —
every close is manual, which is why tickets go stale here. Converting them to
real issues is ticketed.

Re-derive the IDs if they drift:

```sh
gh api graphql -f query='{ user(login:"dcltdw"){ projectV2(number:6){ id
  field(name:"Status"){ ... on ProjectV2SingleSelectField { id options { id name } } } } } }'
```

## After a PR merges

Steps 3 and 5 are the ones that have actually failed here; the rest are cheap.

1. `git checkout main && git pull --ff-only`.
2. **Verify `main` contains the change** — grep for it. "The PR says merged" is
   a different claim: M3's #47 was squash-merged from a state *before* a fix
   commit, so `main` silently lacked it and it had to be cherry-picked back.
3. **Move the board card** → Done, or Won't Do + reason. Skipping this is why
   "M3 PR-2 hardening" sat in Todo for a whole milestone after PR #52 had
   shipped all three of its fixes.
4. **What did this unblock?** Dependent tickets and PRs.
5. **What did this make stale?** Docs describing the old behaviour, tickets the
   merge silently resolved, open PRs needing a rebase, and live config that now
   differs from `main`. Config changes almost always orphan a doc claim.
6. Update durable state: the session ledger, and memory if milestone-level.
7. If it touched infra: verify the live AWS state matches `main`.
8. If it ends a chain: confirm nothing billable is running (`aws eks
   list-clusters`, and the sweep at the end of `scripts/demo-down.sh`).
9. Delete the merged branch, local and remote. **`git branch --merged` will not
   list it** — a squash-merged branch shares no commits with `main`, so the
   obvious command silently misses exactly the branches this repo creates.
