<!-- doc-status: dated -->

# ADR-0011: The documentation-accuracy practice — docs have tests

- Status: accepted
- Date: 2026-07-18

## Context

The repo's principle is that every doc claim links to something a reader can
verify. The fact-check pilot (PR #68) showed care alone fails: 14 inaccuracies
across 6 of 8 audited docs. The two clean docs were clean because their
subject matter is already under automated test — claims stay true when their
source of truth is tested, not when authors are careful. Full design:
[the spec](../superpowers/specs/2026-07-17-docs-accuracy-practice-design.md).

## Decision

Four layers (details and error taxonomy in the spec):

1. **Link integrity** (`check_doc_links.py`) — every internal link and
   #anchor in every tracked doc outside the frozen `docs/superpowers/` archive
   resolves; the archive is exempt because frozen work orders link files that
   do not exist until implemented. PR-blocking; file list derived by glob.
2. **Registered facts** (`check_doc_facts.py`) — load-bearing claims carry an
   in-place annotation (command + expected value + tier). `tier=pr` reads only
   repo files and blocks PRs (and re-runs on every main push — the merge-race
   net). `tier=scheduled` may touch network/live state and runs weekly,
   filing a `docs-accuracy` issue on failure — never gating a PR. An
   adjacency rule binds each annotation to its prose so neither drifts alone.
3. **Human review** (`/docs-fact-check`) — the judgment layer: monthly
   (automated reminder), after milestone-sized merges, on demand before
   sharing. `make docs-checks` is the mechanical sweep that precedes it.
4. **Taxonomy** — every in-scope doc declares `<!-- doc-status: living|dated|
   historical -->`. Facts live only in living docs. Dated/historical docs are
   never edited to match current code — updating a record of the past would
   make it wrong.

**The load-bearing rule.** Register a claim only if (1) it states a specific
verifiable value, (2) a reader finding it wrong would distrust the doc, and
(3) it survived the mandatory triage: **delete → soften to estimate → detie
to a CI-tested source → register.** Registration is last resort; the set
stays small (~5–10). Deliberately NOT registered: the cost/duration
estimates (labeled estimates; measured figure ticketed), "all four
milestones shipped" (terminal state), the CI job list (already detied).

**The override.** `Docs-Checks-Override: <reason>` in a PR body downgrades
Layer-1/2 failures to warnings for that PR only. Main-push and scheduled runs
ignore overrides — the debt surfaces there and in the weekly issue until a
follow-up clears it. The override cannot expand the command allowlist and
cannot authorize edits to dated docs.

## Consequences

- Editing a registered number means editing prose + annotation together; the
  red CI message says exactly that. Small authoring friction, bought: the
  "four vs three" class of error now fails a check instead of shipping.
- The annotation grammar cannot hold nested double quotes; complex commands
  become small helpers under `.github/scripts/` (e.g. `fact_demo_runs.py`).
- A wrong-but-registered claim fails loudly; an unregistered wrong claim
  still relies on Layer 3. The triage rule is what keeps that residue small.
- Every gating checker was watched to fail before merge (red-run links in
  PRs A and B) — a check nobody has seen fail is not yet a check.
