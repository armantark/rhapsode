# Rhapsode

Rhapsode is a local-first app for memorizing passages for exact spoken recall.
Instead of treating every line as an isolated flashcard, it teaches new
material gradually, schedules retrieval with FSRS, practices transitions
between lines, and builds toward uninterrupted recitation.

It is designed for poetry, scripture, speeches, lyrics, and other text that
must be reproduced in order across languages and scripts.

## What makes it different

- **A staged learning runway.** A new line begins with an encounter and word-bank
  reconstruction, then returns across spaced sessions as cumulative three-word
  chunks, end-to-front fading, front-to-end fading, half-word cues, and
  first-letter cues. Oral and typed attempts are interspersed, and each stage
  must be demonstrated before the next appears.
- **Passage-aware practice.** Rhapsode drills line-to-line junctures, forward and
  backward chains, arbitrary starting points, weak links, and complete
  recitations rather than only isolated cards.
- **FSRS scheduling.** Review timing responds to self-graded recall, while a
  daily queue prioritizes weak links, learning material, and due reviews.
- **Recall-supporting annotations.** Translations, glosses, grammar, meter,
  source references, personal mnemonic notes, and reference audio remain
  available without replacing retrieval.
- **Multilingual text support.** The data model handles hierarchical passages
  and token-level annotations across scripts. Japanese text includes local
  tokenization and furigana support; Ancient Greek preserves accents and vowel
  quantity marks.
- **Local ownership.** The desktop and browser development versions use a local
  SQLite database, local media, automatic snapshots, and no authentication.

## Learning flow

```text
Encounter and rebuild
        ↓
Cumulative three-word chunks
        ↓
Fade support from the end
        ↓
Fade support from the front
        ↓
Half-word cues
        ↓
First-letter cues
        ↓
Varied retrieval, chaining, and full recitation
```

Good or Easy answers advance the guided learning stages. Again or Hard keeps
the learner at the current support level. The planner introduces at most two
new units per smart session so unfamiliar material does not arrive as a wall.

## Quick start

### Prerequisites

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 or newer
- npm

From the repository root:

```bash
./scripts/run-dev.sh
```

The script installs the backend and frontend dependencies, applies database
migrations, and starts:

- Web app: http://127.0.0.1:5173/
- API: http://127.0.0.1:8000/api/v1
- Interactive API docs: http://127.0.0.1:8000/docs

Press `Ctrl-C` to stop both processes. Application data is written under
`backend/data/`, which is ignored by Git.

### Start each service separately

Backend:

```bash
cd backend
uv sync --all-groups
uv run rhapsode-migrate
uv run rhapsode
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`. Set
`RHAPSODE_API_TARGET` to use another backend address.

## Optional configuration

Rhapsode works without an external AI service. The optional preparation
assistant can draft translations, glosses, and recall cues when a Gemini API
key is added in Settings or supplied as `GEMINI_API_KEY`.

Runtime paths and server settings use the `RHAPSODE_` prefix:

| Variable | Default | Purpose |
| --- | --- | --- |
| `RHAPSODE_DATABASE_URL` | `sqlite:///data/rhapsode.db` | SQLite database |
| `RHAPSODE_MEDIA_DIR` | `data/media` | Uploaded and reference audio |
| `RHAPSODE_BACKUP_DIR` | `data/backups` | Startup and pre-migration snapshots |
| `RHAPSODE_HOST` | `127.0.0.1` | Backend bind address |
| `RHAPSODE_PORT` | `8000` | Backend port |

For off-machine durability, point `RHAPSODE_BACKUP_DIR` at a synced folder.
Do not commit `.env` files or API keys.

## Architecture

| Area | Technology | Role |
| --- | --- | --- |
| Backend | FastAPI, Pydantic, SQLAlchemy, Alembic | Contract-first API and domain behavior |
| Scheduling | py-fsrs | Review timing and retention |
| Storage | SQLite with WAL | Passages, sessions, attempts, and review state |
| Frontend | SvelteKit, Svelte 5, TypeScript | Browser and desktop interface |
| Desktop | Tauri 2, Rust, PyInstaller | Native shell and bundled Python sidecar |
| Contract | OpenAPI | Generated frontend API types |

The API lives under `/api/v1`. Passage revisions are immutable after practice
begins, session plans are persisted for restart-safe practice, and mutations
are protected with idempotency keys. Personal notes remain mutable overlays so
the learner can change a mnemonic without rewriting the practiced source.

## Development checks

Backend:

```bash
cd backend
uv run pytest
uv run ruff check .
uv run mypy src
uv run python ../scripts/generate_openapi.py --check
```

Frontend:

```bash
cd frontend
npm test
npm run check
npm run build
npm run test:e2e
```

After an API schema change, regenerate the typed frontend contract:

```bash
cd frontend
npm run generate:client
```

## Desktop build

Build the Python sidecar from `backend/`, then package the desktop app:

```bash
cd backend
uv run python ../scripts/build_backend_sidecar.py
cd ../frontend
npm run tauri:build
```

The release workflow in `.github/workflows/desktop-release.yml` builds draft
macOS and Windows artifacts from tags matching `desktop-v*` or `v*`. Signing,
notarization, and final device validation remain platform-local release steps.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI application, migrations, domain services, and tests |
| `frontend/` | SvelteKit UI, Tauri shell, Vitest tests, and Playwright flows |
| `contracts/` | OpenAPI contract and multilingual fixtures |
| `scripts/` | Development, corpus, packaging, and verification utilities |
| `memory-bank/` | Durable product decisions and implementation context |

