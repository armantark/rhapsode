# Frontend To Backend Handoff

## Frontend Status

The SvelteKit frontend is complete and verified against the generated OpenAPI
contract. All routes, components, and utilities are implemented, tested, and
type-checked with zero errors.

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
