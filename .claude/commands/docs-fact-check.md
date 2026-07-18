# /docs-fact-check — Layer-3 documentation review (ADR-0011)

The judgment layer of the documentation-accuracy practice. Run monthly (a
reminder issue is opened automatically), after any milestone-sized merge, or
before sharing the repo with a reader.

## Procedure

1. **Mechanical sweep first:** run `make docs-checks` (link integrity + all
   registered fact tiers). Fix or ticket anything red before proceeding —
   the human pass must not waste attention on machine-checkable drift.
2. **Scope:** the living docs — the `LIVING` set in
   `.github/scripts/check_doc_facts.py` is the source of truth for the list.
   Dated and historical docs are checked ONLY for internal accuracy (broken
   claims about their own time) and are NEVER edited to match current code.
3. **Adversarial audit, one agent per doc:** dispatch a subagent per living
   doc with the instruction: "Verify every factual claim in this doc against
   its source (the file, config, API, or command output it describes). You
   are trying to prove the doc WRONG. Report each finding with the claim,
   the source checked, and the evidence." Include the error taxonomy from
   the spec (`docs/superpowers/specs/2026-07-17-docs-accuracy-practice-design.md`
   § "Error-taxonomy coverage") so agents know the drift classes.
4. **Verify findings before acting:** re-check every reported finding against
   the source yourself. Agents produce false positives; the pilot's rule is
   controller-verified corrections only.
5. **Corrections are their own PR** (never mixed with feature work), using the
   repo's PR-body headings. For each corrected claim, apply the triage order
   before re-writing a number: delete → soften to estimate → detie to a
   CI-tested source → register a fact annotation.
6. **Close the loop:** ticket anything deferred; close the reminder issue with
   a one-line result ("N findings / M corrected / clean").

## Honesty rules

- "Fix the claim, not the phrasing you first noticed" — grep for every
  restatement of a corrected fact across all docs.
- Estimates must be labeled as estimates; a rough figure stated as measured
  fact is a finding even when the number is roughly right.
