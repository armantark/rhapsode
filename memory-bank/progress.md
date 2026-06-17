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
- Collections backend implemented: ordered passage membership, active-revision
  due/learning/new rollups, CRUD/member reorder endpoints, and collection-wide
  sessions with a shared smart cap/time budget and revision-scoped grading.
- Collections backend gates green: 42 pytest, Ruff, strict mypy, migration
  preservation/backfill checks, and regenerated OpenAPI contract.
- Added per-segment personal-note overlays with GET/PUT endpoints, a
  segment-owned migration, and note-over-drafted-cue practice hint precedence.
- Personal-note backend gates green: 45 pytest, Ruff, strict mypy, regenerated
  OpenAPI contract check, migrated startup smoke test, and PinchTab Swagger
  verification.

- Desktop backend sidecar packaging: PyInstaller spec + build script, frozen
  Alembic path resolution, runtime `RHAPSODE_*` env support, desktop-only CORS,
  and backend tests. Handoff documented in
  `memory-bank/handoffs/backend-to-frontend.md`.

- Collections frontend shipped: `/collections` list with due/learning/new
  rollups + create, `/collections/{id}` deck tree (add/remove/reorder/rename/
  delete) and a collection practice launcher that sends `collection_id`
  (preserving modes, segment_kinds, due_only, minutes). The practice page now
  switches the active revision per item via `PracticeItemRead.revision_id`, so a
  collection session keeps each passage's segments/profile/audio in context.
- Collections frontend gates green: svelte-check clean, 62 unit/integration
  tests (added collection client + RollupBadges suites), and 9/9 Playwright e2e
  (new collections-flow spec + cue-model fixes to practice-flow). Manually
  verified end to end in a browser.

- Personal-notes frontend shipped: inline note editor on the practice card with
  `getNote`/`putNote` client methods (404 = no note), live note-over-drafted-hint
  precedence behind the existing "Need a hint?" reveal, and in-place save without
  a session rebuild. Covered by client + PromptCard unit tests and a notes-flow
  Playwright spec; 68 unit/integration tests and 10/10 functional e2e green.
- Reconciled the dev-DB migration drift (dropped empty orphan collection/note
  tables, ran `alembic upgrade head`); backend boots on the dev DB again.

- Tauri v2 desktop shell shipped in `frontend/src-tauri`: sidecar spawn/kill,
  health polling, `api_base_url()` command, `initApiBase()` in layout, debug
  fallback to external backend on port 8000.
- GitHub Actions draft release workflow (`.github/workflows/desktop-release.yml`)
  with macOS arm64/Intel + Windows matrix; sidecar built via
  `scripts/build_backend_sidecar.py` before `tauri build`.
- Integration reconciliation: unified build script naming, `RHAPSODE_DESKTOP=1`
  on sidecar spawn, CI `uv sync` + Python sidecar build, git remote
  `https://github.com/armantark/rhapsode.git`.
- Desktop sidecar smoke script (`scripts/desktop_sidecar_smoke.py`) verifies
  health + passage listing without launching Tauri.
- All gates green (2026-06-12): 57 backend pytest, ruff, mypy, openapi check;
  72 frontend vitest, svelte-check, build; `cargo check`; sidecar smoke pass.
- Added abandoned-session lifecycle and smart-exercise variety: active sessions
  expire after 24 idle hours and leave the default list; direct stale links show
  an expired state. Smart planning now balances least-used useful exercises per
  line/mastery stage, including forward/backward chaining, random starts, and
  reference-audio shadowing while keeping junctures transition-focused.
- Verified the lifecycle/variety pass with 61 backend tests, Ruff, strict mypy,
  contract check, 72 frontend tests, svelte-check, build, 12/12 Playwright, and
  PinchTab against the real Iliad/dev database.
  Four stale active sessions were expired and a fresh smart plan visibly
  contained random-start and forward-chaining exercises.

## Remaining

- Push to GitHub and trigger first tagged draft release.
- Code signing / notarization (macOS) and Windows Authenticode (optional).
- Manual install validation on packaged `.dmg`/installer artifacts.
- Point `RHAPSODE_BACKUP_DIR` at a synced (iCloud) folder when launching.
- Extend the reference-audio URL map beyond Iliad 1.1-100 as practice grows.
- Prose chunk drafting via LLM is deferred until a prose passage exists.
