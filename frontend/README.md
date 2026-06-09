# Annotated Maps — Frontend

React + TypeScript PWA (Vite) for Annotated Maps. See the [root README](../README.md) for full setup and the design docs under `docs/`.

## Commands (run from `frontend/`)
- `npm install` — install deps (an `.npmrc` pins `legacy-peer-deps`)
- `npm run dev` — dev server (expects the API at `/api/v1`; set `VITE_API_BASE` to override)
- `npm run test -- --run` — Vitest component tests
- `npm run lint` — ESLint (incl. jsx-a11y)
- `npm run build` — production build (emits the PWA service worker + manifest)
