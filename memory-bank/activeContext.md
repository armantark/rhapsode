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
  revealed/incorrect/hesitant/clean. Showing the answer is a NEUTRAL self-check
  (Anki model): it never forces a grade. The peek is recorded as an
  informational `revealed` flag on the attempt, independent of the rating.
- Every attempt stores a `review_snapshot` (prior review state of each segment
  it touched), so `POST /sessions/{id}/undo` rolls the last card back exactly —
  re-opens the item, rewinds FSRS/mastery, and reactivates a just-completed
  session. Cmd/Ctrl+Z drives it from the practice page, repeatable to the start.
- Grade feedback is "juicy": a per-grade colour pulse + tuned Web Audio tone
  (rising scale Again→Easy), a session-complete arpeggio, and a sound toggle
  (`rhapsode.soundEnabled`). All animations honour prefers-reduced-motion.
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
- Chamberlain's CC-BY recitation was removed (too unlike the teacher's reading
  to shadow). We now work from the teacher's own recording. `CuePoint` gained
  optional `segment_id` + `end`; `scripts/align_reference_audio.py` derives
  per-line cue spans from pauses (ffmpeg silencedetect). During shadowing the
  player auto-seeks and loops the practised line's span. Pause auto-detect is
  heuristic and did NOT cleanly fit the teacher's 26s file (first span swallowed
  ~2 lines); a manual "tap line starts" UI is the reliable follow-up.
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
- Build a manual line-alignment affordance (play teacher audio, tap at each
  line start) that PUTs segment-linked cues — the reliable path, since
  pause auto-detect under-segments the teacher's recording.
- LLM-assisted chunking for prose passages is deferred until a prose passage
  exists (grill B4/C1).
