# Progress

## Completed

- Product and backend implementation plan agreed.
- Repository initialized on `feat/rhapsode-backend`.
- Persistence models, Alembic baseline, services, and `/api/v1` routes implemented.
- Built-in language profiles and plugin extension registries implemented.
- Backend unit, API, restart-recovery, media, and end-to-end tests implemented.
- Backend-to-frontend handoff and multilingual fixture requests created.
- Generated OpenAPI contract and verified it against the application.
- All 17 backend tests, Ruff, strict mypy, migrations, snapshots, and live HTTP
  smoke checks pass.
- SvelteKit frontend implemented: generated client, library, editor, practice,
  review, and all four scripts.
- Frontend unit, integration, and end-to-end tests implemented (44 passing).
- `svelte-check` reports 0 errors and 0 warnings; production build succeeds.
- Full integration cycle verified: passage creation, session, grading, session
  completion, and analytics all work through the Vite dev proxy.
- Frontend-to-backend handoff note created with requested contract additions.
- Manual browser testing via Pinchtab completed.
- Added filtered media listing, durable audio cue points, and paginated mastery
  endpoints.
- Added a cue-point migration that preserves existing media rows.
- Regenerated OpenAPI and verified the completed frontend remains compatible.

- Coach features implemented end to end: smart sessions (mastery-driven mode
  selection per segment, 12-item cap with triage), due-only sessions launched
  from the review tab, and hesitation latency surfaced in weak links.

## Remaining

- Frontend should regenerate its API client and remove the media registry,
  cue-point, and far-future mastery local workarounds.
- Two Playwright microphone tests remain blocked by fake microphone permission
  timeouts; the four non-microphone e2e workflows pass.
