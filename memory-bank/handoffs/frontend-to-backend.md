# Frontend To Backend Handoff

## Frontend Status

The SvelteKit frontend is complete and verified against the generated OpenAPI
contract. All routes, components, and utilities are implemented, tested, and
type-checked with zero errors.

## Initial Acquisition UI (2026-07-14)

- `PromptCard` renders `acquisition` as one internal encounter → reconstruct →
  produce sequence. The encounter uses the existing rich segment tree; the
  reconstruction must place every supplied chip before showing the true line;
  production hides the bank and shows only the deterministic lead-in.
- The practice page locks keyboard reveal and grading until production, then
  requires the ordinary answer reveal before a grade. All internal phase,
  chips, and check state reset on the persisted practice-item id, including
  when an undone generated retry reopens.
- `PRACTICE_MODES` remains the manual-launcher inventory and intentionally
  excludes contract mode `acquisition`. The Playwright smart-progression spec
  now exercises the composite flow and confirms junctures still fade.

Run it from `frontend/`:

```bash
npm install
npm run dev
```

The Vite dev server proxies `/api` to the backend at `http://127.0.0.1:8000`.

## Verified Results

- `npm test`: 44 unit/integration tests pass (7 suites).
- `svelte-check`: 0 errors, 0 warnings.
- `npm run build`: production build succeeds via `@sveltejs/adapter-static`.
- Full integration cycle (create passage, start session, grade two items,
  complete session, verify analytics) confirmed through both programmatic API
  calls and manual Pinchtab browser testing.

## Integration Observations

### Working smoothly

- Idempotency-key stamping: every mutation includes a unique key; retries
  replay the same key. The single-retry on network failure for mutations works.
- 409 conflict detection: the frontend correctly catches `ApiError` with
  status 409 and offers a fork-revision flow when a practiced revision is
  edited.
- Session recovery: the backend persists `current_index` and per-item
  `completed` flags; the frontend stores a localStorage pointer to the
  in-flight session. A browser crash or reload resumes at the right item.
- Language profiles: all four profiles (Ancient Greek, Classical Armenian,
  Latin, Japanese) seed correctly on first run. Font stacks, language tags,
  annotation schemas, and display options all flow through to the renderer.

### Requested contract additions

All three requested additions are implemented on
`feat/rhapsode-contract-additions`.

1. **Media listing endpoint.** The contract has `POST /media` (upload),
   `DELETE /media/{id}`, and `GET /media/{id}/content` but no index. The
   frontend works around this with a `localStorage` registry
   (`src/lib/utils/mediaRegistry.ts`), but a `GET /api/v1/media` endpoint
   (with optional `revision_id` and `category` query filters) would eliminate
   the client-side registry and make media survive browser data clears.
   **Implemented:** `GET /api/v1/media` with optional `revision_id` and
   `category` filters.

2. **Cue-point persistence.** Audio cue points are browser-local
   (`localStorage`). A `cue_points` field on the media model or a separate
   `/api/v1/media/{id}/cues` sub-resource would make them durable.
   **Implemented:** `MediaRead.cue_points` plus idempotent
   `PUT /api/v1/media/{id}/cues`.

3. **Review-state index.** The frontend fetches all mastery data by calling
   `GET /api/v1/analytics/due?before=2999-01-01T00:00:00Z`. A dedicated
   `GET /api/v1/analytics/mastery` with pagination would be cleaner for large
   corpora.
   **Implemented:** `GET /api/v1/analytics/mastery` with limit/offset
   pagination and `{ items, total, limit, offset }` response metadata.

### Edge cases noted

- Fixture payloads in `contracts/fixtures/` use placeholder language profile
  IDs (`LANGUAGE_PROFILE_ID_ANCIENT_GREEK`). Consumers must resolve the actual
  profile ID from `GET /api/v1/languages` by slug before submitting.

- Creating a passage without calling "Generate line segments" in the editor
  now falls back to `autoSegment`, which splits on newlines. This means the
  backend always receives at least one segment, avoiding empty-segment errors.

## Collections Frontend (2026-06-10)

The collection/deck tree and collection practice launcher are implemented and
verified against the regenerated contract. No backend schema or behavior changes
were needed; the additions in `## Contract Additions Implemented` were sufficient.

What the frontend now does:

- `/collections` lists collections with their `rollup` (due/learning/new) and a
  create form (`POST /collections`).
- `/collections/{id}` renders `members` in `position` order, supports add
  (`POST .../members`), remove (`DELETE .../members/{passage_id}`), reorder
  (`PUT .../members` with the full `passage_ids` order), rename/delete, and a
  practice launcher.
- The launcher sends exactly one of `revision_id` (passage page) or
  `collection_id` (collection page), preserving `modes`, `segment_kinds`,
  `due_only`, and `minutes`.
- The practice page loads every revision a session touches and switches the
  active revision per item using `PracticeItemRead.revision_id`, so segments,
  language profile, and reference audio always match the card. The session list
  and recovery pointer resolve a title from `collection_id` when present.

### Resolved: dev-DB migration drift

- The dev DB previously failed to boot with `table collections already exists`:
  it had `collections`, `collection_passages`, and `personal_notes` (all empty)
  whose schemas matched the migrations, but `alembic_version` was stuck at
  `a1f2c3d4e5f6`. Fixed by dropping the three orphan tables and running
  `alembic upgrade head`, which replays `b7c8d9e0f1a2 (add_collections)` and
  `c8d9e0f1a2b3 (add_personal_notes)` cleanly. The backend now boots on the dev
  DB (`/health` and `/collections` return 200). No data was lost.

## Personal Notes Frontend (2026-06-11)

Inline personal-note authoring is implemented on the practice card and verified
against the contract; no backend changes were needed.

- New client methods: `getNote(segmentId)` (treats `404` as `null`, not an
  error) and `putNote(segmentId, text)` (idempotency-keyed).
- The card fetches the live note for the current segment on every item. Hint
  precedence is note-first, then the persisted `prompt.hint` drafted-cue
  fallback — both stay behind the existing "Need a hint?" reveal so recall
  integrity is unchanged.
- The note editor saves through `PUT` and updates the card in place (no session
  rebuild). "Add a note" is offered even when a segment has no drafted hint.
- No contract issues found.

### Contract observations (no change requested)

- `SessionRead.items` is optional (absent from `required`); the frontend guards
  with `session.items ?? []`. Fine as-is.
- `revision_id`/`collection_id` on `SessionRead` and `revision_id` on
  `PracticeItemRead` are nullable; the frontend treats a null `revision_id` as a
  collection session. Fine as-is.
- Collection manual sessions offer `segment_kinds` chips `line/chunk/token/
  section`; we rely on the backend to drop kinds a given passage lacks. Confirm
  that mixed-kind requests across heterogeneous passages are handled gracefully.

## Architecture Notes for Backend Dev

The frontend is intentionally stateless except for:
- `localStorage.rhapsode.activeSession.v1`: recovery pointer (session id,
  revision id, passage title, timestamp).
- `localStorage.rhapsode.media.v1`: uploaded media index (workaround for
  missing listing endpoint).
- `localStorage.rhapsode.cues.<mediaId>`: audio cue points.

All three can be safely wiped; the only consequence is that media uploaded
before the wipe will not appear in the UI until the listing endpoint lands.

## Desktop / Tauri Frontend (2026-06-12)

Tauri v2 scaffolding lives in `frontend/src-tauri/`. The Rust shell:

1. Reserves a localhost port and sets backend env vars under the OS app data dir:
   `RHAPSODE_PORT`, `RHAPSODE_DATA_DIR`, `RHAPSODE_DATABASE_URL`,
   `RHAPSODE_MEDIA_DIR`, `RHAPSODE_BACKUP_DIR`.
2. Spawns sidecar `binaries/rhapsode-backend-<target-triple>`.
3. Polls `GET /api/v1/health` until 200.
4. Exposes `api_base_url()` → `http://127.0.0.1:{port}/api/v1`.
5. Kills the sidecar on app exit.

Debug builds fall back to `http://127.0.0.1:8000/api/v1` when the sidecar binary
is missing (for `tauri dev` with `uv run rhapsode` running separately).

### Backend contract (reconciled 2026-06-12)

| Item | Status |
|------|--------|
| Sidecar basename | `rhapsode-backend` → `frontend/src-tauri/binaries/rhapsode-backend-<target-triple>` (`.exe` on Windows) |
| Build script | `uv run python scripts/build_backend_sidecar.py --target-triple <triple>` from repo root |
| Health probe | `GET /api/v1/health` → 200 |
| Desktop CORS | `RHAPSODE_DESKTOP=1` enables Tauri webview origins (Rust sets this on spawn) |
| Frozen paths | Alembic + bundled data resolve inside PyInstaller output |
| Env vars | Honor existing `RHAPSODE_*` settings in `config.py` |

### Notes

- `Cargo.lock` pins `time = 0.3.47` to avoid Rust 1.95 / `time 0.3.48` E0119; revisit when upstream fixes land.
- Sidecar smoke without Tauri: `uv run python scripts/desktop_sidecar_smoke.py --require-sidecar` after building the sidecar.

Frontend API discovery: browser dev unchanged (`/api/v1` proxy); Tauri awaits
`initApiBase()` in `+layout.svelte` before rendering. CI:
`.github/workflows/desktop-release.yml` builds the sidecar via
`scripts/build_backend_sidecar.py` before `tauri build`.

## Session Lifecycle UI (2026-06-12)

- The existing `SessionRead.status` string is sufficient for expiry; no schema
  addition was requested.
- A direct link to an expired session now shows a dedicated "Session expired"
  card and disables undo instead of reusing the completion celebration.
- The normal Sessions page needs no filtering change because the backend omits
  expired sessions from the default listing.
- Playwright now covers the visible smart progression from progressive fading
  to cue recall, forward chaining, and backward chaining on a learning line.

## Japanese Reading UI (2026-06-21)

- No API shape change was needed. The frontend consumes existing `SegmentRead`
  token children and `AnnotationRead.data.render === "ruby"`.
- For Japanese line nodes with token children, `SegmentText` now hides the
  duplicate whole-line surface and renders the token row as the primary reading
  surface. Each token can show ruby from its own `reading` annotation and gloss
  underneath when the gloss layer is enabled.
- Practice cards treat Japanese ruby as baseline reading support, not a
  translation/gloss toggle. Progressive fading renders the full-support stage
  through `SegmentText`, and checked Japanese answers render ruby even when no
  support layers are enabled.
- Whole-line ruby remains as a fallback for older Japanese passages with a
  line-level `reading` annotation and no token children.
- Manual smoke used an isolated local backend/frontend and verified a seeded
  Japanese passage rendered token-level furigana and glosses through PinchTab.
