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

