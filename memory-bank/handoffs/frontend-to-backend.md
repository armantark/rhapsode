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

1. **Media listing endpoint.** The contract has `POST /media` (upload),
   `DELETE /media/{id}`, and `GET /media/{id}/content` but no index. The
   frontend works around this with a `localStorage` registry
   (`src/lib/utils/mediaRegistry.ts`), but a `GET /api/v1/media` endpoint
   (with optional `revision_id` and `category` query filters) would eliminate
   the client-side registry and make media survive browser data clears.

2. **Cue-point persistence.** Audio cue points are browser-local
   (`localStorage`). A `cue_points` field on the media model or a separate
   `/api/v1/media/{id}/cues` sub-resource would make them durable.

3. **Review-state index.** The frontend fetches all mastery data by calling
   `GET /api/v1/analytics/due?before=2999-01-01T00:00:00Z`. A dedicated
   `GET /api/v1/analytics/mastery` with pagination would be cleaner for large
   corpora.

### Edge cases noted

- Fixture payloads in `contracts/fixtures/` use placeholder language profile
  IDs (`LANGUAGE_PROFILE_ID_ANCIENT_GREEK`). Consumers must resolve the actual
  profile ID from `GET /api/v1/languages` by slug before submitting.

- Creating a passage without calling "Generate line segments" in the editor
  now falls back to `autoSegment`, which splits on newlines. This means the
  backend always receives at least one segment, avoiding empty-segment errors.

## Architecture Notes for Backend Dev

The frontend is intentionally stateless except for:
- `localStorage.rhapsode.activeSession.v1`: recovery pointer (session id,
  revision id, passage title, timestamp).
- `localStorage.rhapsode.media.v1`: uploaded media index (workaround for
  missing listing endpoint).
- `localStorage.rhapsode.cues.<mediaId>`: audio cue points.

All three can be safely wiped; the only consequence is that media uploaded
before the wipe will not appear in the UI until the listing endpoint lands.
