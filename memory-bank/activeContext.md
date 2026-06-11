# Active Context

## Current Focus

The collections backend is implemented on top of the 2026-06-10 practice
system. Existing passages can now be grouped in an ordered collection, viewed
with an Anki-style rollup, and launched as one practice target. The frontend
collection/deck tree remains the next handoff.

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
- `minutes` is a TARGET, not just a ceiling. When one full pass leaves budget
  on the clock (short passage, generous time), the leftover buys extra varied
  repetitions: each segment walks `FILL_MODE_CYCLE`
  (progressive_fading→cue_recall→random_start, skipping its own primary mode),
  dealt highest-triage-first and presented as further passage-order
  run-throughs. The rotation length caps reps per segment so a tiny passage is
  never ground to death by a long budget; a budget that binds in the first pass
  is unaffected.
- Review UNITS are only the practiced kinds (`planning.practiceable_kinds`:
  grain + juncture). Word `token` segments carry interlinear glosses but are
  never drilled, so full-passage grading no longer fans review states onto
  them, and both due paths (the `/analytics/due` listing and `due_only`
  sessions) ignore non-practiceable kinds. This fixed the "Target has no
  practiceable segments" 422 that stranded "Practice N due" when stale token
  states from an earlier full-passage grade surfaced as permanently-due.
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
- Every practice instruction states its recitation EXTENT (no open-ended
  "continue"): shadowing/fading recite the whole line; chaining goes through to
  the last line / the ending; cue-recall, weak-link and random-start recite the
  line to the end; junctures recite only into the next line's opening (their
  target is the head); full-passage is start to finish. `random_start` is now a
  CHECKABLE cold start — it reuses the recall shape (`_recall_prompt`): a short
  lead-in is shown, the full line is the revealed answer, framed as an arbitrary
  drop-in entry point to break serial-order dependence (it was previously a
  full-line display with no reveal). The card renders it like cue_recall and it
  is in the reveal/Space allow-lists.
- Recall cues are POSITIONAL+VERBATIM, not LLM-authored: `_lead_in` in
  `planning.py` slices the line's opening words (keeps δ᾽/elisions exact). The
  evocative phrase (often LLM-drafted) is demoted to an optional `hint` the
  learner reveals with "Need a hint?". Rationale: an LLM can't author a learner's
  personal cross-language associations ("boulē → tabouleh"); only the
  deterministic opening is safe to automate.
- Personal notes now provide that learner-owned mnemonic layer without forking
  a practiced revision. `GET/PUT /segments/{id}/note` reads or upserts the
  mutable overlay, and newly built recall/weak-link prompts prefer its text over
  the revision-owned drafted cue. The note model and endpoints do not touch the
  prep LLM, scheduling, or grading.
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
- Collections group existing passages without owning revisions. Reads and
  session launches resolve member passages' active revisions; collection
  sessions persist that revision snapshot and apply one shared smart cap or
  minutes budget across the union.

## Verified Results

- Backend: 50 pytest, ruff, strict mypy, contract `--check` all green.
- Frontend: 69 vitest, svelte-check 0/0, Playwright e2e green.
- Live Gemini call drafted 5 cues + 5 glosses + 5 translations onto the real
  Iliad passage; quality checked by hand (accurate glosses, natural
  translations).
- Junctures backfilled onto the practiced Iliad revision (+4) via
  `scripts/backfill_junctures.py`; Chamberlain's CC-BY recitation of Iliad
  1.1-100 imported as reference audio via `scripts/import_reference_audio.py`.

## Next Work

- Build the frontend deck tree and collection launcher against the collection
  contract documented in `handoffs/backend-to-frontend.md`.
- First-letter fade cue mode (initials only) as a lighter trigger than the full
  lead-in; pairs with progressive fading.
- Wire the personal-note endpoints into an inline practice-card note editor.
  Prefer the latest fetched note over the persisted prompt hint so edits also
  appear immediately in an already-created session.
- Verify the manual aligner end-to-end on the teacher's real recording and
  confirm shadowing auto-jumps to each saved line span.
- Set `RHAPSODE_BACKUP_DIR` to an iCloud-synced path in the launch command.
- LLM-assisted chunking for prose passages is deferred until a prose passage
  exists (grill B4/C1).
- Parked: curated recorded SFX (synth tones are zero-dependency and graded).
