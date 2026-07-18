# Documentation-accuracy practice — design

- **Date:** 2026-07-17
- **Status:** Approved design, pre-implementation
- **Design input:** [issue #71](https://github.com/dcltdw/annotated-maps-sp/issues/71)
  (the design brief distilled from the fact-check pilot, PR #68)

## Problem

The repo's stated principle is that every documentation claim links to something
a reader can verify. Nothing enforces that but care, and the fact-check pilot
proved care isn't enough: 14 inaccuracies across 6 of 8 audited docs. The two
clean docs were clean because their subject matter is *already under automated
test* — the central insight this design builds on.

The test any mechanism here must pass: it would have caught a run-count that
said "four" when the real number was three.

**Correction to the brief:** the living-docs set is now **seven**, not eight —
PR #69 reframed `docs/architecture/2026-06-09-production-lenses.md` as a dated
historical snapshot. The living docs: `README.md`, `ROADMAP.md`,
`docs/for-reviewers.md`, `docs/aws-primer.md`, `docs/kubernetes-primer.md`,
`docs/DEPLOY.md`, `docs/slos.md`.

## Goals / non-goals

**Goals**

- Deterministic, repo-local doc claims are enforced on every PR.
- Network- or state-backed claims are checked on a schedule and surface as
  issues, never as red PR CI.
- The human/agent fact-check review is repeatable: documented, scheduled, and
  invocable on demand.
- The living / dated / historical taxonomy is machine-readable and enforced.
- Every check has been watched to fail before the practice is called done.

**Non-goals**

- External-URL liveness never gates a PR (the demo sleeps; spurious reds train
  people to ignore CI).
- No automated process ever edits a dated or historical doc.
- No attempt to register every number — over-registration rots, and a stale
  check lies about coverage.

## Architecture — four layers

Mirrors the repo's existing check patterns: small Python scripts in
`.github/scripts/` invoked as CI steps, plus a grouped `make` target that runs
the same commands CI runs.

### Layer 1 — link integrity (PR-blocking)

`.github/scripts/check_doc_links.py`. Every internal link and `#anchor` in
every Markdown doc — living *and* dated; internal accuracy applies to all —
must resolve. **Exception (amended during implementation):** the
`docs/superpowers/` plan/spec archive is out of scope, matching its taxonomy
exemption — frozen work orders routinely link files that do not exist until
implemented, so gating them would redden every future plan PR. The file set
is derived by glob at runtime, never hand-maintained (a hand-kept list
already rotted once in this repo). External URLs are excluded here; they
belong to the scheduled job.

### Layer 2 — registered facts (split by determinism)

`.github/scripts/check_doc_facts.py` scans **living docs only** for in-place
annotations and executes them. Two tiers:

- **`pr` tier** — the command reads only files in the repo (quoted config
  values, file inventories, CI job counts, cross-doc consistency). Runs as a
  PR-blocking CI step, and again on every push to `main` (see "Concurrency"
  below). Deterministic: it cannot fail for reasons unrelated to the repo's
  own state.
- **`scheduled` tier** — the command needs network or live state (GitHub API
  run counts, environment settings). Runs in the scheduled workflow; on
  failure it opens/updates a tracking issue. Never gates a PR, because this
  state drifts independently of any PR.

### Layer 3 — human/agent review (judgment, deliberately not CI)

The pilot procedure codified as a repo slash command,
`.claude/commands/docs-fact-check.md`: adversarial per-doc audit, findings
re-verified against source before any correction, corrections as their own PR.
Triggers:

1. **Monthly** — the scheduled workflow opens a reminder issue.
2. **After any milestone-sized merge** — policy line in `CLAUDE.md`.
3. **On demand** — `make docs-checks` runs every mechanical check locally
   (Layers 1 + 2, both tiers) as the last-minute pre-reader sweep, with
   `/docs-fact-check` as the judgment layer on top.

### Layer 4 — policy (ADR-0011)

`docs/adr/0011-documentation-accuracy-practice.md` (next free slot, verified)
records the practice, the taxonomy, and the load-bearing rule. A short rule in
`CLAUDE.md` points to it.

**Taxonomy, machine-readable and in-place:** every doc opens with a marker —
`<!-- doc-status: living -->`, `dated`, or `historical`. The checker enforces:
every doc under the glob declares exactly one status; fact annotations appear
only in living docs (an annotation in a dated doc is an error); dated and
historical docs are never edited by any automated process.

## Annotation format

One HTML comment (invisible when rendered) on the line immediately above the
claim:

```markdown
<!-- fact: tier=pr cmd="yq '.jobs | length' .github/workflows/ci.yml" expect="6" -->
Every push runs six CI jobs...
```

Checker behavior, per annotation:

1. Parse `tier`, `cmd`, `expect`, optional `prose`.
2. Validate `cmd` against a **binary allowlist** — pr tier: `grep`, `ls`, `wc`,
   `cat`, `yq`, `jq`, `git`, `python3` (repo scripts only); scheduled tier
   adds `gh` and `aws`. Anything else is a hard error.
3. Execute; compare trimmed stdout to `expect`.
4. **Adjacency rule:** `expect` (or `prose` when the claim is written in words,
   e.g. `prose="six"`) must appear in the prose within the next 3 lines.
   Editing the prose without the annotation fails; editing the annotation
   without the prose fails. Neither drifts silently.

**Failure output:** doc, line, the claim text, expected vs. actual, and the fix
instruction — "update the prose *and* the annotation, or re-run the command to
re-derive the value."

## The load-bearing rule

Register a claim only when **all three** hold:

1. It states a specific verifiable value — count, version, cost, or enumerated
   list — about the repo, its infrastructure, or its history.
2. A reader could independently check it, and finding it wrong would reasonably
   make them distrust the rest of the doc.
3. It survived triage.

**Mandatory triage order — registration is last resort:**

1. **Delete** the number if it adds nothing.
2. **Soften** to an explicit estimate if it's an estimate.
3. **Detie** — rewrite so the claim links to or derives from an already-tested
   source (the mechanism that kept the two clean docs clean).
4. **Register** the residue with an annotation.

Expected registered set after triage: **~5–10 facts** (the brief counted
roughly a dozen candidates before triage). If implementation finds the set
ballooning past ~15, that's a signal to re-triage, not to register more.

## Scheduled workflow

`.github/workflows/docs-accuracy.yml`, two crons:

- **Weekly:** run scheduled-tier facts + external-URL liveness (retry with a
  generous timeout — the Render demo sleeps and takes ~30 s to wake), plus
  the full pr-tier suite against `main` — so drift that slipped past the gate
  (override, merge race, missed red run) lands in a tracked issue rather than
  only a transient red build. On failure, open or update a single tracking
  issue; never fail a PR.
- **Monthly:** open the Layer-3 review reminder issue.

## Concurrency and merge races

Within one PR there is no race by construction: pr-tier commands read only
files in the same checkout as the docs, so claim and source are compared at
the same commit.

The real exposure is **cross-PR merge ordering**: PR A changes a source file
and its annotation (green); concurrent PR B, branched before A merged, is
green against the old base; branches are not required to be up to date, so a
merge combination can land on `main` that no PR ever tested. The net:
**Layers 1 and 2 (pr tier) also run on every push to `main`.** A red main run
means merge ordering — not any single PR — introduced drift; the response is a
small fix-forward PR. (A merge queue would prevent this outright but is
machinery out of proportion for a solo repo — noted and rejected.)

Scheduled-tier lag — live state drifting for up to a week before the cron
notices — is a design property, not a race; that is exactly why those checks
file issues instead of gating.

## Override escape hatch

For when the checks are right in principle but blocking necessary work — e.g.
a multi-PR doc restructure that is transiently inconsistent mid-flight — a PR
body line (mirroring the `check_pr_body.py` pattern):

```
Docs-Checks-Override: <mandatory reason>
```

When present, the Layer 1 and Layer 2 PR steps report their failures as
warnings and exit green **for that PR only**, echoing the reason in the CI
log. Two properties keep it honest:

- **Defer, never erase.** Main-push and scheduled runs ignore overrides, so
  anything overridden past the gate surfaces immediately on `main`'s run and
  in the weekly tracking issue. The debt is tracked until a follow-up PR
  clears it.
- **Outcomes only.** The override downgrades check failures. It cannot expand
  the command allowlist and cannot authorize edits to dated or historical
  docs — those rules hold unconditionally.

## Error-taxonomy coverage

Mapping the brief's eight drift classes to layers:

| Class | Covered by |
|---|---|
| 1 wrong-count-of-a-record | scheduled-tier fact (`gh`) |
| 2 doc-quotes-a-value-that-changed | pr-tier fact |
| 3 doc-describes-state-that-changed | pr-tier (repo config) or scheduled-tier (live state) |
| 4 capability-shipped-but-doc-says-not-yet | Layer 3 + doc-status marker forces the doc to declare intent |
| 5 claim-of-a-thing-only-ever-planned | pr-tier fact (codebase grep) |
| 6 stale-inventory | pr-tier fact (directory listing) |
| 7 stale-count-of-behaviour | pr-tier fact (workflow file) |
| 8 estimate-stated-as-fact | consistency half: pr-tier cross-doc fact; wording half: Layer 3 |

The brief's litmus case (four-vs-three run count) is caught by a scheduled-tier
fact within a week and by Layer 3 at review time.

## Testing & acceptance

- Unit tests for the checkers (parser, allowlist rejection, adjacency rule,
  taxonomy enforcement), following the existing `.github/scripts/` style.
- `make docs-checks` runs the same commands CI runs.
- **Non-negotiable acceptance:** each PR that delivers a CI-gating checker
  includes a commit that breaks what it checks (an internal link for Layer 1;
  a registered fact for Layer 2), links to the red CI run proving it fails
  *for the right reason*, then reverts. A check nobody has watched fail isn't
  done.

## Rollout shape (input to the implementation plan)

Small single-purpose PRs, roughly:

1. Layer 1 link checker + CI wiring + `make docs-checks` (partial).
2. Layer 2 checker + doc-status markers + the triaged annotations in the seven
   living docs + CI wiring + the watched-failure demonstration.
3. `docs-accuracy.yml` scheduled workflow.
4. Layer 3 slash command + ADR-0011 + `CLAUDE.md` policy line.

Board: move the parent card ("Durable documentation-verification practice") to
In Progress; the pilot card is complete (PRs #68/#69) and should move to Done.
