# Active Context

## Current Focus

The frontend-requested backend contract additions are implemented and ready for
the frontend to remove its media, cue-point, and mastery workarounds.

## Active Decisions

- Local-first single-user app with no authentication.
- Python 3.13 and SQLite WAL.
- Trusted reference audio and saved-best recordings are the only persisted audio.
- Self-grading is canonical; speech scoring remains an extension point.
- All language-specific assistance is optional and profile/plugin driven.
- Frontend and backend coordinate through OpenAPI plus fixtures and handoff notes.
- Session recovery remains intentionally browser-local. Media discovery, cue
  points, and mastery pagination are now backend-owned.

## Verified Results

- Backend: `uv run pytest -q` (20 pass), `ruff check .` (clean), `mypy src`
  (clean), OpenAPI contract matches, live HTTP smoke checks pass.
- Frontend: `npm test` (44 pass), `svelte-check` (0 errors), `npm run build`
  (succeeds), full API integration cycle confirmed, Pinchtab manual testing
  confirmed.
- Contract additions: existing-media migration preserves rows with empty cue
  points; live API verification covered media filtering, cue replacement, and
  paginated mastery.
- PinchTab confirmed the generated Swagger UI exposes the three additions.
- Playwright: four non-microphone workflows pass; two microphone workflows fail
  because the browser's fake microphone permission times out.

## Next Work

- Frontend: regenerate the TypeScript client and replace the three localStorage
  workarounds with the new endpoints.
- Resolve the local Playwright fake-microphone permission failure separately.
