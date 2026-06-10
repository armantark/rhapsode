# Technical Context

- Python 3.13, `uv`
- FastAPI 0.136.x, Pydantic v2
- SQLAlchemy 2.0.x, Alembic
- SQLite with foreign keys and WAL mode
- Py-FSRS 6.3.x
- Pytest, Ruff, mypy

Development commands run from `backend/`:

```bash
uv sync --all-groups
uv run alembic upgrade head
uv run rhapsode
uv run pytest
uv run ruff check .
uv run mypy src
uv run python ../scripts/generate_openapi.py --check
```

The production entry point runs Alembic and seeds built-in language/plugin
profiles before serving. The API requires an `Idempotency-Key` header for every
mutation.

