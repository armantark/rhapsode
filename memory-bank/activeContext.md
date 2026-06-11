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
  ~2 lines), so the reliable path is now the manual `LineAligner.svelte` on a
  passage's reference audio: play, tap `M` at each line start, save per-line cue
  spans via `PUT /media/{id}/cues` (client `setMediaCues`).
- Recall cues are POSITIONAL+VERBATIM, not LLM-authored: `_lead_in` in
  `planning.py` slices the line's opening words (keeps δ᾽/elisions exact). The
  evocative phrase (often LLM-drafted) is demoted to an optional `hint` the
  learner reveals with "Need a hint?". Rationale: an LLM can't author a learner's
  personal cross-language associations ("boulē → tabouleh"); only the
  deterministic opening is safe to automate.
- Flashcard annotation layers: the practice page renders the practised segment's
  subtree via `SegmentText` (reusing the reading view), so translation/gloss/meter
  show interlinearly WHEN the answer is revealed (recall integrity preserved).
  Toggles persist in `rhapsode.practiceLayers`; the `cue` layer is excluded.
- Space reveals the answer (neutral self-check) for recall modes; juice is now
  graded — distinct per-grade tones on a "brighter = better" scale, clean-streak
  escalation (`playGrade(rating, streak)`), eased card-enter + dot pop + 🔥 streak
  chip, all reduced-motion safe. Grounded in juicy-feedback research (success-
  dependent, coherent, not over-amplified).
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

- DECK GROUPING (needs Arman's decision; see
  `status-updates/cues-annotations-grouping-roadmap-2026-06-10.html`). Recommended
  option A: a "collection" model grouping existing passages (Iliad 1.1–5 + 1.6–10)
  with an Anki-style due/learning/new rollup, and a session that can target a
  whole collection or one passage. Backend slice first (new model + endpoints +
  `session.collection_id`), then a frontend deck tree. Hand-off prompt is in the
  artifact.
- First-letter fade cue mode (initials only) as a lighter trigger than the full
  lead-in; pairs with progressive fading.
- Inline "edit hint" on the flashcard so a mnemonic invented mid-practice sticks
  to the line immediately (today the hint is editable only in the editor).
- Verify the manual aligner end-to-end on the teacher's real recording and
  confirm shadowing auto-jumps to each saved line span.
- Set `RHAPSODE_BACKUP_DIR` to an iCloud-synced path in the launch command.
- LLM-assisted chunking for prose passages is deferred until a prose passage
  exists (grill B4/C1).
- Parked: curated recorded SFX (synth tones are zero-dependency and graded).
