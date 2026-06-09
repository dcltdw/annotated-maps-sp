# ADR-0002: Tech stack — Django + Ninja backend, React PWA frontend
- Status: accepted
- Date: 2026-06-09
## Context
Solo build by a Python-strong developer; cheap hosting (~$7/mo); API-first for web + future native; self-implemented auth on vetted libraries.
## Decision
Django + Django Ninja (typed API + OpenAPI) on PostgreSQL; React + TypeScript PWA via Vite. See spec §3.
## Consequences
Maximizes time in Python; Django auth primitives back the self-implemented auth; one typed API serves all clients.
