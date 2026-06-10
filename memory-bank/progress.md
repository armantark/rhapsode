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
- 2026-06-10 grill decisions implemented in one pass: time-budgeted smart
  sessions (minutes → item count via personal per-mode latency), focus-paused
  latency clock, consecutive-clean mastery with regression, difficulty decay,
  auto-generated juncture segments (+ backfill script), one-grain planner,
  opt-in mic, API-backed reference audio listing, scholar recitation import
  (Chamberlain Iliad 1.1-100, CC-BY), startup/pre-migration DB snapshots, and
  a Gemini 3.1 Pro prep assistant (cue/gloss/translation drafts, verified
  live against the real passage).
- Iliad meter annotations imported from Chamberlain's scansion data
  (vendored CSVs, CC-BY) via `scripts/import_meter.py`.
- All gates green: 33 backend tests, ruff, strict mypy, contract check,
  47 frontend unit tests, svelte-check clean, 7/7 Playwright e2e.

## Remaining

- Point `RHAPSODE_BACKUP_DIR` at a synced (iCloud) folder when launching.
- Extend the reference-audio URL map beyond Iliad 1.1-100 as practice grows.
- Prose chunk drafting via LLM is deferred until a prose passage exists.
