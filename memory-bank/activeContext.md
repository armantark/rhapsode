# Active Context

## Current Focus

The 2026-06-10 grill decisions (see `decisions-grill-2026-06-10.md`) are fully
implemented across backend and frontend in one pass, per Arman's "do it all at
once" ruling. The app is now ready for real daily Iliad practice.

## Active Decisions

- Local-first single-user app with no authentication.
- Python 3.13 and SQLite WAL; startup + pre-migration snapshots (24h gate,
  keep 14) in `services/backup.py`; point `RHAPSODE_BACKUP_DIR` at a synced
  folder for off-machine durability.
- Grading is Anki-labeled (Again/Hard/Good/Easy keys 1-4) mapping to
  revealed/incorrect/hesitant/clean.
- `clean_count` on review states holds CONSECUTIVE cleans; mastery stages can
  regress (Again resets, Hard demotes one step). Difficulty flags decay after
  2 consecutive cleans.
- Junctures (line N tail → line N+1 head) are auto-generated segments of kind
  `juncture` in `add_segments`; never authored, never rendered in reading or
  editor views, but planned and reviewed like any segment.
- Smart sessions: one grain per passage (chunks if present, else lines, plus
  junctures), 12-item cap or an optional `minutes` budget converted via
  per-mode mean attempt latency (defaults until ≥5 samples). Finisher is
  budgeted first when the passage is fully graduated.
- Frontend latency clock counts focused time only (pauses on blur/hidden).
- Mic is opt-in (`rhapsode.micEnabled`); reference audio listing is now
  API-backed (`GET /media`) so script-imported scholar audio appears.
- LLM prep assistant: Gemini `gemini-3.1-pro-preview` (the only API id for
  3.1 Pro), key from repo-root `.env` as `GEMINI_API_KEY`. Prep-only: drafts
  cue/gloss/translation, never overwrites authored content, practice loop has
  no LLM dependency.

## Verified Results

- Backend: 33 pytest, ruff, strict mypy, contract `--check` all green.
- Frontend: 47 vitest, svelte-check 0/0, 7/7 Playwright e2e green.
- Live Gemini call drafted 5 cues + 5 glosses + 5 translations onto the real
  Iliad passage; quality checked by hand (accurate glosses, natural
  translations).
- Junctures backfilled onto the practiced Iliad revision (+4) via
  `scripts/backfill_junctures.py`; Chamberlain's CC-BY recitation of Iliad
  1.1-100 imported as reference audio via `scripts/import_reference_audio.py`.

## Next Work

- Set `RHAPSODE_BACKUP_DIR` to an iCloud-synced path in the launch command.
- Extend `AUDIO_URLS` in `import_reference_audio.py` as more line ranges are
  needed (archive.org item ids vary per book).
- LLM-assisted chunking for prose passages is deferred until a prose passage
  exists (grill B4/C1).
