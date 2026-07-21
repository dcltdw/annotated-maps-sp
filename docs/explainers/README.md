<!-- doc-status: dated -->

# Explainers

Understanding-oriented documentation. If the rest of the docs tree tells you
**what** was decided (`docs/adr/`), **what** to build (`docs/superpowers/specs/`
and `plans/`), or **how** to run something (`README.md`, `docs/*-primer.md`),
the files here answer a different question: **why does this work the way it
does, and what does it all mean** — explained from the ground up, assuming very
little prior knowledge.

These are the docs to read when the mindset is *"understand what already
exists"* rather than *"build the next thing."* They narrate a finished piece of
the system top to bottom, define their terms, and prefer a slow, complete
explanation over brevity. They link out to the specs, ADRs, and source they
describe rather than duplicating them — the source stays the authority; the
explainer is the guided tour.

## How this directory is organized

Two axes, kept deliberately separate:

- **Domain — the subdirectory.** Each explainer lives in the folder matching the
  part of the codebase it explains, so it is always the obvious neighbor of the
  code it describes. Planned domains, created when their first explainer lands
  (git does not track empty directories, so a domain folder appears with its
  first file):
  - `infra/` — the `deploy/` layer: Terraform, Helm, Kubernetes/EKS, Render, the
    ephemeral demo pipeline, observability.
  - `backend/` — the Django/PostGIS application.
  - `frontend/` — the Vite/TypeScript application.

  A topic that genuinely spans layers (auth, the demo pipeline end to end) lives
  in its *primary* domain and links across, rather than in a catch-all folder. A
  dedicated cross-cutting bucket gets introduced only if a real cluster of
  pan-domain explainers ever needs one — not pre-built.

- **Kind — a filename prefix.** Within a domain, two kinds of explainer:
  - **`foundation-…`** — a ground-up primer on a *technology or concept* you need
    before the walkthroughs make sense (e.g. AWS IAM, React, Django). Read once.
    The `foundation-` prefix clusters these together in every listing; **read the
    relevant foundation before its walkthroughs.**
  - everything else — a **walkthrough** of one specific built thing in this
    codebase (e.g. a particular subsystem or design), which assumes its domain's
    foundations.

## Conventions

- **`doc-status: dated`.** An explainer is a snapshot: true as of its date, a
  narrative of the system as it stood then. Per ADR-0011 it is never mechanically
  edited to track code changes — if the code moves far enough that the tour
  misleads, the honest fix is a new explainer (or a dated note at the top), not a
  silent rewrite of the story.
- **Self-contained.** A reader should be able to follow an explainer without
  first reading the spec it describes. Shared background is factored into a
  `foundation-` primer that the walkthroughs build on.
- **Links, not copies.** Facts and decisions live in their canonical homes
  (ADRs, specs, code). Explainers point at them.
- **Describe what is, not how it got there.** No build-history asides ("this
  fixed…", "we used to…", "closed a hole") — that's provenance, not explanation.
  An explainer reads as if the system was always this way.
- **Diagram interactions.** Prefer a fenced ```mermaid diagram for structural or
  interaction relationships (how the pieces connect / a decision flow) — it
  renders on GitHub and stays text-diffable. Keep each diagram scoped to the
  explainer's subject; a full domain-wide entity-relationship diagram belongs in
  that domain's model/foundation explainer.

## Index

Explainers as they land, Foundations-first.

<!-- Maintenance: when adding an explainer, add a linked entry here — under
     Foundations if its filename is foundation-*, otherwise under Walkthroughs
     with its domain as the lead-in. -->

### Foundations (read first)

- [The visibility model](backend/foundation-visibility-model.md) *(backend)* —
  the app's signature idea: per-section, per-viewer access resolved by a small
  pure engine into visible/teaser/hidden. Viewer, the four rule types, the
  fail-closed rule mapping, and how a request wires it together. The vocabulary
  the backend walkthroughs assume.
- [AWS IAM from zero](infra/foundation-aws-iam.md) *(infra)* — accounts, roles,
  ARNs, the Allow/Deny model, assuming a role, instance profiles and instance
  metadata, `PassRole`, service-linked roles, permissions boundaries, and OIDC
  federation. The identity vocabulary the infra walkthroughs assume.

### Walkthroughs

- **infra** — [The deployer permissions boundary](infra/deployer-permissions-boundary.md):
  the IAM privilege-escalation problem in the AWS demo pipeline (issue #109) and
  the permissions-boundary design that closes it — what
  "AdministratorAccess-equivalent" really means here, the "Path B" escalation
  told as a story, and a guided reading of every piece of the fix.
