# Active Context

## Current Focus

Both backend and frontend lanes are complete. The frontend is verified against
the backend through unit tests, type checks, API integration tests, and manual
browser testing.

## Active Decisions

- Local-first single-user app with no authentication.
- Python 3.13 and SQLite WAL.
- Trusted reference audio and saved-best recordings are the only persisted audio.
- Self-grading is canonical; speech scoring remains an extension point.
- All language-specific assistance is optional and profile/plugin driven.
- Frontend and backend coordinate through OpenAPI plus fixtures and handoff notes.
- Frontend uses localStorage for media registry, cue points, and session
  recovery until the backend provides listing/persistence endpoints.

## Verified Results

- Backend: `uv run pytest -q` (17 pass), `ruff check .` (clean), `mypy src`
  (clean), OpenAPI contract matches, live HTTP smoke checks pass.
- Frontend: `npm test` (44 pass), `svelte-check` (0 errors), `npm run build`
  (succeeds), full API integration cycle confirmed, Pinchtab manual testing
  confirmed.

## Next Work

- Backend: implement the three requested contract additions from
  `memory-bank/handoffs/frontend-to-backend.md`.
- Run the Playwright e2e suite once a dedicated backend instance on port 8643
  is available.
