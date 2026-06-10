# Technical Context

## Backend

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

## Frontend

- SvelteKit 2.63.x, Svelte 5.56.x (runes mode)
- Vite 8.0.x, TypeScript 5.9.x (strict)
- `@sveltejs/adapter-static` for SPA output
- openapi-typescript for generated client types
- Vitest 4.1.x, @testing-library/svelte 5.3.x for unit/integration
- Playwright 1.60.x for e2e

Development commands run from `frontend/`:

```bash
npm install
npm run dev
npm test
npm run build
npx svelte-check --tsconfig ./tsconfig.json
npm run generate:client
npx playwright test
```

The Vite dev server proxies `/api` to the backend via `server.proxy`. Override
with `RHAPSODE_API_TARGET` env var.
