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

- Board: https://github.com/users/dcltdw/projects/6 (`PVT_kwHOAAdfes4Bcevp`)
- Status field `PVTSSF_lAHOAAdfes4BcevpzhXHOIs`:
  Todo `f75ad846`, In Progress `47fc9ee4`, Done `98236657`

Re-derive if these drift:

```sh
gh api graphql -f query='{ user(login:"dcltdw"){ projectV2(number:6){ id
  field(name:"Status"){ ... on ProjectV2SingleSelectField { id options { id name } } } } } }'
```
