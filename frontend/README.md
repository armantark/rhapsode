# Rhapsode Frontend

SvelteKit UI for [Rhapsode](https://github.com/armantark/rhapsode): a local-first oral memorization app for exact spoken recall across languages and scripts.

The web app is a static SPA (`@sveltejs/adapter-static`). In development, Vite proxies `/api` to the FastAPI backend. The desktop app is a Tauri v2 shell that bundles the same UI and spawns the Python backend as a sidecar.

## Prerequisites

- Node.js 22+
- npm (lockfile is committed)
- For browser development: Python backend running from `backend/` (see repo root docs)
- For desktop builds: Rust stable, platform build tools, and a built backend sidecar binary

## Browser development

From `frontend/`:

```bash
npm install
npm run dev
```

Start the backend separately from `backend/`:

```bash
uv sync --all-groups
uv run rhapsode-migrate
uv run rhapsode
```

The dev server listens on `http://localhost:5173` and proxies `/api` to `http://127.0.0.1:8000`. Override the proxy target with `RHAPSODE_API_TARGET`.

## Desktop development

`npm run tauri:dev` launches the Tauri webview against the Vite dev server. On startup, Rust tries to spawn `src-tauri/binaries/rhapsode-backend-<target-triple>`. If the sidecar is missing in debug builds, it falls back to an external backend at `http://127.0.0.1:8000` (run `uv run rhapsode` in another terminal).

```bash
npm run tauri:dev
```

## API base URL

- **Browser / Vite:** the client uses same-origin `/api/v1` through the dev proxy.
- **Tauri:** Rust reserves a localhost port, sets `RHAPSODE_*` env vars for the sidecar, waits for `GET /api/v1/health`, then exposes `api_base_url()` to the frontend via `@tauri-apps/api/core`.

See `src/lib/api/platform.ts` and `src-tauri/src/lib.rs`.

## Building the desktop app

1. Build the backend sidecar from the repo root (copies into `src-tauri/binaries/`):

   ```bash
   uv run python ../scripts/build_backend_sidecar.py
   ```

   For compile-only stubs before the real binary exists:

   ```bash
   ../scripts/create-sidecar-stub.sh
   ```

2. Build the desktop bundle:

   ```bash
   npm run build
   npm run tauri:build
   ```

Release artifacts are produced by `.github/workflows/desktop-release.yml` on version tags (`desktop-v*` or `v*`).

## Quality gates

```bash
npm test              # Vitest unit/integration
npm run check         # svelte-check
npm run build         # static production build
npm run test:e2e      # Playwright (requires backend + frontend servers)
```

Regenerate the typed API client after OpenAPI changes:

```bash
npm run generate:client
```

## Project layout

| Path | Purpose |
|------|---------|
| `src/routes/` | SvelteKit pages (library, editor, practice, review, collections) |
| `src/lib/api/` | Generated schema + hand-written API client |
| `src/lib/components/` | Shared UI (practice card, audio, segments) |
| `src-tauri/` | Tauri config, Rust sidecar lifecycle, bundled backend binary slot |
| `e2e/` | Playwright specs |

Contract source of truth: `../contracts/openapi.json`.
