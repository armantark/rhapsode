# Rhapsode Backend

Local-first FastAPI backend for Rhapsode.

```bash
uv sync --all-groups
uv run rhapsode-migrate
uv run rhapsode
```

The API is served at `http://127.0.0.1:8000/api/v1`. Every mutation requires an
`Idempotency-Key` header.

