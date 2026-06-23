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
- Discover persisted media through `GET /api/v1/media`, with optional
  `revision_id` and `category` filters. The local media registry can be removed.
- Persist audio cue points through `PUT /api/v1/media/{id}/cues`. Cue points are
  returned in `MediaRead` and sorted by time by the backend.
- Resume interrupted practice by fetching the session id and honoring
  `current_index`, item order, and each item's `completed` field.
- Render prompt behavior from `PracticeItem.mode` and `PracticeItem.prompt`.
  The prompt payload is intentionally open-ended for plugin modes.
- Personal notes are separate from immutable revision/segment reads. Treat a
  `404` from `GET /api/v1/segments/{segment_id}/note` as "no personal note";
  `PUT` upserts one and requires an `Idempotency-Key`.

## Main Workflows

1. Fetch language profiles from `GET /api/v1/languages`.
2. Create a passage with its first revision through `POST /api/v1/passages`.
3. Create later immutable revisions through `POST /api/v1/passages/{id}/revisions`.
4. Upload trusted audio through `POST /api/v1/media`.
5. Start a guided practice plan through `POST /api/v1/sessions`.
6. Render each persisted practice item and submit one of `clean`, `hesitant`,
   `incorrect`, or `revealed` through `POST /api/v1/sessions/{id}/attempts`.
7. Use `/api/v1/analytics/due` for due reviews,
   `/api/v1/analytics/mastery?limit=50&offset=0` for paginated mastery, and
   `/api/v1/analytics/weak-links` for difficult segments.

## Contract Additions Implemented

- Collections are available through `GET/POST /api/v1/collections` and
  `GET/PUT/DELETE /api/v1/collections/{collection_id}`.
- Add a passage with `POST /api/v1/collections/{collection_id}/members`
  using `{ "passage_id": "..." }`; remove it with
  `DELETE /api/v1/collections/{collection_id}/members/{passage_id}`; reorder
  all members with `PUT /api/v1/collections/{collection_id}/members` using
  `{ "passage_ids": ["...", "..."] }`.
- `CollectionRead.members` is position-ordered and includes passage summaries.
  `CollectionRead.rollup` exposes mutually exclusive `{ due, learning, new }`
  counts over each member passage's active revision and default practice grain.
- `POST /api/v1/sessions` now accepts exactly one of `revision_id` or
  `collection_id`. Collection sessions preserve existing `modes`,
  `segment_kinds`, `due_only`, and `minutes` options; `PracticeItemRead` carries
  its `revision_id` so the frontend can retain passage context while traversing
  a collection session.
- `GET /api/v1/media?revision_id={id}&category={reference|saved_best}`
  returns persisted media newest-first.
- `MediaRead.cue_points` contains ordered `{ label, time }` records.
- `PUT /api/v1/media/{media_id}/cues` replaces the asset's cue points and
  requires `Idempotency-Key`.
- `GET /api/v1/analytics/mastery?limit={1..200}&offset={n}` returns
  `{ items, total, limit, offset }`.
- `GET /api/v1/segments/{segment_id}/note` returns
  `{ segment_id, text, updated_at }` when a personal note exists.
- `PUT /api/v1/segments/{segment_id}/note` upserts `{ "text": "..." }` even
  when the segment's revision is already practiced. It never mutates the
  segment cue or forks the revision.
- Newly created cue-recall and weak-link practice items put the personal note
  in `prompt.hint` when one exists, falling back to the revision-owned cue. For
  an inline editor on an already-created session, fetch the latest note for the
  current `segment_id` and prefer it over the persisted fallback prompt hint.

## Session Lifecycle And Smart Variety (2026-06-12)

- Active sessions expire after 24 idle hours. `GET /sessions` expires stale
  rows and omits `status=expired` by default; `GET /sessions?status=expired`
  exposes them when needed. Direct session reads still return the persisted
  plan/items with `status: "expired"`.
- Expired sessions reject new attempts and undo. Frontends should render them
  as abandoned history, not as completed practice.
- The API shape is unchanged. Smart plans now use attempt history to select the
  least-used useful exercise for each line's mastery stage. Chaining prompts
  always carry a continuous passage context, and junctures never receive
  forward/backward chaining.

## Japanese Prep Tokens And Ruby (2026-06-21)

- `POST /api/v1/revisions/{revision_id}/prep-suggestions` still returns the
  same `{ written }` shape and remains prep-only; the generated OpenAPI contract
  did not change.
- The default prep layers still include `reading` in addition to `cue`, `gloss`,
  and `translation`, but Japanese ruby no longer requires Gemini. Revision
  create/replace and prep `reading` use local fugashi + unidic-lite tokenization
  to fill `reading` annotations with `{ "render": "ruby" }` for
  kanji-containing Japanese tokens.
- Gemini structured output remains useful for token/word glosses and
  translations, but the prompt now lists local Japanese token boundaries in
  `<words>` so glosses can attach by word index. Authored token children,
  readings, and glosses are not overwritten; authored readings are the override
  for dictionary-mismatched lyric/name readings.
- Existing passages with only line-level reading annotations continue to work.
- These tokens remain support structure for reading/interlinear display; the
  line remains the practice recall target and the Gemini model id is unchanged.

## Desktop / Tauri Sidecar (2026-06-12)

The backend can run as a PyInstaller sidecar spawned by the Tauri host. Browser
dev mode is unchanged: Vite still proxies same-origin `/api/v1`.

### Sidecar binary

- Build script: `uv run python scripts/build_backend_sidecar.py` from repo root.
- PyInstaller spec: `backend/rhapsode-sidecar.spec`.
- Output copied to `frontend/src-tauri/binaries/rhapsode-backend-<target-triple>`
  (`.exe` suffix on Windows). Tauri `externalBin` should reference the base name
  `binaries/rhapsode-backend`; Tauri appends the host triple automatically.
- Entry point: the existing `rhapsode` CLI (`rhapsode.cli:main`) — migrate,
  snapshot, seed defaults, then bind Uvicorn.

### Runtime environment (set by Tauri before spawn)

| Variable | Purpose |
| --- | --- |
| `RHAPSODE_HOST` | Bind address (default `127.0.0.1`) |
| `RHAPSODE_PORT` | Loopback port chosen by the host |
| `RHAPSODE_DATA_DIR` | App data root |
| `RHAPSODE_DATABASE_URL` | SQLite URL, e.g. `sqlite:///<data>/rhapsode.db` |
| `RHAPSODE_MEDIA_DIR` | Uploaded audio storage |
| `RHAPSODE_BACKUP_DIR` | Startup/pre-migration snapshots |
| `RHAPSODE_DESKTOP` | Set `1`/`true` to enable desktop CORS |
| `RHAPSODE_CORS_ORIGINS` | Optional comma-separated override of default Tauri origins |

When `RHAPSODE_DESKTOP=1`, the API adds CORS for `tauri://localhost`,
`https://tauri.localhost`, and `http://tauri.localhost`. Override with
`RHAPSODE_CORS_ORIGINS` if the webview origin differs.

### Health check

Poll `GET http://127.0.0.1:<RHAPSODE_PORT>/api/v1/health` until
`{"status":"ok",...}`. All other routes remain under `/api/v1` as documented in
`contracts/openapi.json`.

### Frontend contract for Tauri mode

1. Reserve or pick a free localhost port; export the env vars above (including
   `RHAPSODE_DESKTOP=1`) before spawning the sidecar.
2. Spawn `rhapsode-backend-<target-triple>` via Tauri `ShellExt::sidecar`.
3. Expose the resolved API base (`http://127.0.0.1:<port>/api/v1`) to Svelte
   through a Tauri command such as `api_base_url()`.
4. In browser/dev mode, keep using relative `/api/v1` through the Vite proxy.
5. Kill the sidecar on app shutdown.

### Build matrix target triples

- macOS Apple Silicon: `aarch64-apple-darwin`
- macOS Intel: `x86_64-apple-darwin`
- Windows x64: `x86_64-pc-windows-msvc`

Cross-compile is not handled by the build script; CI should run the script on
each platform runner with `--target-triple` matching that runner.

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
