# Backend To Frontend Handoff

## Backend Status

The backend is implemented under `backend/`. Its generated source of truth is
`contracts/openapi.json`; representative multilingual request payloads live in
`contracts/fixtures/`.

Run it from `backend/`:

```bash
uv sync --all-groups
uv run rhapsode-migrate
uv run rhapsode
```

The service binds to `http://127.0.0.1:8000`. Interactive OpenAPI documentation
is available at `http://127.0.0.1:8000/docs`.

## Contract Rules

- Generate the TypeScript client from `contracts/openapi.json`.
- Do not infer request or response shapes from database models.
- Send a unique `Idempotency-Key` on every mutation. Reuse that key when
  retrying the same operation.
- Treat passage revisions as immutable after any session starts. If a segment
  replacement returns `409`, create a new revision instead.
- Persist browser recordings only by uploading them as `saved_best`.
  Unsubmitted attempts remain browser-local and ephemeral.
- `reference` and `saved_best` are the only accepted media categories.
- Resume interrupted practice by fetching the session id and honoring
  `current_index`, item order, and each item's `completed` field.
- Render prompt behavior from `PracticeItem.mode` and `PracticeItem.prompt`.
  The prompt payload is intentionally open-ended for plugin modes.

## Main Workflows

1. Fetch language profiles from `GET /api/v1/languages`.
2. Create a passage with its first revision through `POST /api/v1/passages`.
3. Create later immutable revisions through `POST /api/v1/passages/{id}/revisions`.
4. Upload trusted audio through `POST /api/v1/media`.
5. Start a guided practice plan through `POST /api/v1/sessions`.
6. Render each persisted practice item and submit one of `clean`, `hesitant`,
   `incorrect`, or `revealed` through `POST /api/v1/sessions/{id}/attempts`.
7. Use `/api/v1/analytics/due` and `/api/v1/analytics/weak-links` for review
   and mastery views.

## Frontend Handoff Prompt

```text
Implement the Svelte frontend for Rhapsode using the backend contract and fixtures already present in `contracts/`.

Read every file in `memory-bank/` first, especially `memory-bank/handoffs/backend-to-frontend.md`. Do not modify backend-owned schemas or API behavior without documenting a requested contract change.

Build a desktop-first responsive “scholarly arcade” interface for:
- Passage library and multilingual passage editor
- Hierarchical sections, lines, chunks, tokens, and configurable annotations
- Reference-audio upload, looping, cue points, and playback speed
- Guided resumable oral-practice sessions
- Browser-local ephemeral attempt recording and playback
- Four self-grading actions: clean, hesitant, incorrect, and revealed
- Mastery, due-review, weak-link, and saved-best views
- Greek, Armenian, Latin, and Japanese rendering, including ruby and vertical Japanese

Generate the TypeScript client from `contracts/openapi.json`. Develop against the committed fixtures and backend API. Keep recording ephemeral unless the user explicitly saves a best attempt.

Add frontend unit, integration, and end-to-end tests. Perform manual browser testing with Pinchtab for microphone permissions, Unicode rendering, keyboard navigation, session recovery, and responsive layouts. Leave a frontend-to-backend handoff note for any integration issues.
```

