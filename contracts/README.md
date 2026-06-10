# Rhapsode Backend Contract

`openapi.json` is generated from the FastAPI application and is the source of
truth for frontend client generation.

The fixture files are representative `PassageInput` requests. Their placeholder
language profile ids must be replaced with ids returned by `GET /api/v1/languages`
before submission.

Every `POST`, `PUT`, `PATCH`, and `DELETE` request under `/api/v1` must include a
stable `Idempotency-Key` header. Retrying a completed mutation with the same key,
HTTP method, and path returns the original response with
`Idempotency-Replayed: true`.

Media can be discovered through `GET /api/v1/media`, optionally filtered by
`revision_id` and `category`. Audio cue points are included in every
`MediaRead` and replaced atomically through `PUT /api/v1/media/{id}/cues`.

Use `GET /api/v1/analytics/mastery?limit=50&offset=0` for paginated review-state
listing. `GET /api/v1/analytics/due` remains the due-only scheduling view.
