# Demo Tour (Guided Walkthrough) — Design

- **Date:** 2026-07-04
- **Status:** Approved design, pending implementation plan
- **Slice:** Frontend onboarding tour. Sequences AFTER the richer-seed slice
  (`2026-07-04-richer-seed-data-design.md`) — the tour's payoff step needs the
  richer content to reveal.

## Context

A first-time visitor lands on a map with no explanation of the product's core
idea (per-viewer visibility). The one thing they won't discover unaided is the
"Viewing as" switcher — and watching the map re-filter is the product. The
demo is a marketing surface, so a prominent tour affordance is appropriate
where a production app would use a quieter one-time popup.

## Goals

1. A guided spotlight tour that **performs the persona switch live** — the
   visitor watches pins appear rather than reading that they would.
2. Capture visitors who don't click: auto-start on first visit, plus a
   persistent replay button.
3. Cheap to keep working: stable targeting, e2e-covered, all copy in i18n.

## Non-goals

- No backend/API changes.
- Not a general-purpose onboarding framework — one hand-rolled component for
  this tour.
- The "production variant" (quiet one-time popup, no big button) is a
  documented seam, not built.

## Design

### 1. Component: hand-rolled spotlight overlay

`TourOverlay.tsx` — a full-viewport overlay that dims the page and cuts a
spotlight around the current step's target (four dim rectangles around the
target's `getBoundingClientRect`, or an SVG mask), with a positioned card
(copy, step dots, Back / Next / Skip).

**Why hand-rolled rather than driver.js/react-joyride:** this app is a single
non-scrolling viewport with a handful of fixed targets — the hard parts
libraries solve (scroll tracking, complex positioning) don't apply, the
persona-switch step needs custom behavior anyway, and the codebase's pattern
is minimal dependencies (no router, hand-rolled popovers). driver.js (~5 kB,
MIT) is the documented fallback if the overlay grows past ~200 lines.

Targets are located via `data-tour="…"` attributes on stable containers
(map wrap, PreviewSwitcher, NotePanel, AuthBar) — never on map markers or
other dynamic children, so the tour has no coupling to MapLibre internals.

**Editability requirement:** steps are declared as a data array
(`{target, copyKey, sideEffect?}`), not imperative code — copy edits touch
only `en.json`; adding/reordering a passive step is one array entry (+ a
`data-tour` attribute); only a *new kind* of side effect requires wiring a
callback. e2e asserts behavior (overlay, switch happened, panel opened),
never copy strings, so wording changes don't break tests. The
`tourSeenV1` key doubles as a version lever — bump it to re-show a revamped
tour to returning visitors once.

### 2. Step sequence

| # | Spotlight | Copy gist | Side effect |
|---|---|---|---|
| 0 | none (centered card) | What this is; "20-second tour"; Start / Skip | — |
| 1 | map | "A shared map of Boston. Right now you're a **Guest** — you see only public content." | ensure persona = Guest |
| 2 | Viewing-as switcher | "Everyone sees a different map. This picks whose eyes you borrow." | — |
| 3 | map | "Watch — now you're **A Running Friend**." …"New pins just appeared: friend-only tips and Running-club notes." | **programmatic switch to running-friend** (brief pause between switch and copy so the change is visible) |
| 4 | NotePanel | "One note, many sections — each section has its own audience." | programmatically select the designated showcase note |
| 5 | AuthBar | "Log in as any persona to write notes, or keep exploring. Try the other viewers — the dim sum crowd sees a different city." | — |

On finish/skip: overlay closes, persona **stays** on A Running Friend with the
showcase note open — the visitor lands on the richest view, primed to switch
personas themselves. (Resetting to Guest would demo the product and then hide
it again.)

**Showcase note:** the seed data designates one full-ladder note near map
center; the tour finds it in the already-loaded notes list by title constant.
If absent (e.g. local dev without seed), step 4 is skipped — every step
degrades by skipping, never by crashing.

### 3. Triggering & state

- **Auto-start:** on first visit only — `localStorage["tourSeenV1"]` absent —
  and only after the notes fetch succeeds (never over the "waking up the demo
  server…" retry state), and only when logged out. Set `tourSeenV1` the moment
  the tour opens (start = seen; robust to StrictMode double-mount — the #36
  lesson: gate on state, not call counts).
- **Replay:** a persistent "✦ Take the tour" pill in the topbar, gated on
  `VITE_SANDBOX` — the marketing build shows it; a production build wouldn't.
- **Production seam (documented, not built):** the quiet variant is this exact
  component with the pill hidden — auto-start-once is already the one-time
  popup behavior.

### 4. Interaction & accessibility

- Overlay is `role="dialog"` `aria-modal`; focus moves into the card, is
  trapped, and returns to the trigger on close; Esc skips.
- Underlying UI is inert during the tour (the tour performs the interactions
  itself), so steps can't be broken by stray clicks.
- Repositions on window resize; respects `prefers-reduced-motion` (no
  animated spotlight transitions).
- Copy lives in `en.json` under `tour.*` per the i18n structure rule.

### 5. Testing

- **Unit:** trigger logic (first visit + loaded + logged out → auto-start;
  `tourSeenV1` set on open; replay button always starts), step reducer
  (next/back/skip), showcase-note-absent degradation.
- **e2e:** full walkthrough — assert the overlay appears on first visit,
  step 3 actually changes the rendered markers (persona switch happened),
  step 4 opens the note panel, finish leaves persona = Running Friend, and a
  second page load does NOT auto-start but the pill replays. Reuses the
  existing stateful stub patterns.

### 6. Risks

- **Layout coupling:** mitigated by `data-tour` attributes + the e2e walk.
- **Cold-start race:** auto-start is gated on load success by design.
- **Seed dependency:** step 4 degrades by skipping; the tour is still coherent
  without it (steps 1–3 carry the core lesson).

## Testing summary

`npm run test` (trigger + reducer units) + new `e2e/tour.spec.ts` + existing
suites unchanged.
