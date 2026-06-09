# ADR-0004: Responsive PWA now, native client later
- Status: accepted
- Date: 2026-06-09
## Context
"Usable on web and mobile" with the cheapest hosting and one codebase; native is a showcase option later.
## Decision
Ship one responsive installable PWA over the API-first backend; defer a native client to its own slice.
## Consequences
Fastest path to a usable, cheap demo; the API boundary keeps a native client a clean future add.
