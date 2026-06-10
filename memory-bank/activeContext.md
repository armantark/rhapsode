# Active Context

## Current Focus

The backend lane is complete and ready for a separate Svelte frontend thread.

## Active Decisions

- Local-first single-user app with no authentication.
- Python 3.13 and SQLite WAL.
- Trusted reference audio and saved-best recordings are the only persisted audio.
- Self-grading is canonical; speech scoring remains an extension point.
- All language-specific assistance is optional and profile/plugin driven.
- Frontend and backend coordinate through OpenAPI plus fixtures and handoff notes.

## Verified Results

- `uv run pytest -q`: 17 tests pass.
- `uv run ruff check .`: clean.
- `uv run mypy src`: clean under strict mode.
- `uv run python ../scripts/generate_openapi.py --check`: generated contract matches.
- `uv run rhapsode-migrate` creates the schema and snapshots an existing SQLite database.
- `uv run rhapsode` migrated and served a fresh installation on `127.0.0.1`.
- Live API verification created the Ancient Greek fixture and replayed its
  idempotent mutation.

## Next Work

Implement the Svelte frontend against `contracts/openapi.json` and
`memory-bank/handoffs/backend-to-frontend.md`.
