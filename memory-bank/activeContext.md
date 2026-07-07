# Active Context

## Current Focus

Pedagogy hardening pass (2026-07-06) after merging all feature branches into
main: FSRS lapse mapping, fading direction, due-aware triage, juncture fading
anchor, and check-before-grade. Desktop release validation (signing, first tag
push, install smoke) remains the other open thread.

## Active Decisions

- Local-first single-user app with no authentication.
- Python 3.13 and SQLite WAL; startup + pre-migration snapshots (24h gate,
  keep 14) in `services/backup.py`; point `RHAPSODE_BACKUP_DIR` at a synced
  folder for off-machine durability.
- Grading is Anki-labeled (Again/Hard/Good/Easy keys 1-4) mapping to
  revealed/incorrect/hesitant/clean. Showing the answer is a NEUTRAL self-check
  (Anki model): it never forces a grade. The peek is recorded as an
  informational `revealed` flag on the attempt, independent of the rating.
  Since 2026-07-06 the converse IS enforced: on recall modes (cue_recall,
  random_start, weak_link, chaining, full_passage) the grade bar stays disabled
  until the answer has been shown — verbatim errors are the ones the reciter
  doesn't hear, so grading blind inflated the schedule.
- FSRS lapse mapping (2026-07-06): "incorrect" (the Hard button, "errors in
  recall") schedules as Rating.Again, not Rating.Hard — FSRS treats Hard as a
  successful recall, which grew the interval on exactly the lines just recited
  wrong. The ladder still distinguishes the two failure kinds (grill B2:
  revealed wipes the streak, incorrect demotes one step); only the schedule
  unifies them as lapses. hesitant→Good, clean→Easy are unchanged.
- Progressive fading direction (2026-07-06): support fades from the END of the
  line toward the opening, because the opening is the retrieval cue (_lead_in
  doctrine). Each stage demands a longer recalled tail and the last supported
  stage converges on the cue_recall card shape. Ellipsis units on juncture
  heads are never masked. Japanese token fading in PromptCard mirrors this.
- Juncture fading cards (2026-07-06) carry `lead_in` (the previous line's
  tail) as a persistent gold anchor above the stages, so the tail→head
  association is trained even at the fully faded stage.
- Smart-session triage is due-aware (2026-07-06): rank order is weak links →
  learning → DUE review/durable → new → not-yet-due maintenance. Reviews come
  before new material; not-due maintenance only fills leftover room.
- Two new practice modes (2026-07-06, Arman's ruling — first-letter sprint
  explicitly rejected as useless): `word_bank` deals the line's own units
  (token children when present) as shuffled chips to rebuild in order — serial
  order is the dominant verse failure, so it LEADS the learning-stage rotation
  as the gentlest step above fading; never dealt to junctures (3-word heads
  are trivial) including in the minutes-fill rotation. `typed_recall` joins
  the graduated (review/durable) rotation for lines and junctures: lead-in
  cue, type from memory, then the attempt stays on screen stacked above the
  true line for a VISUAL self-check — nothing is parsed or diffed, ever
  (extends grill D3's self-grading-is-the-instrument to writing). Both are
  recall modes: grade bar locked until the check. Typed text is not stored.
- SCAMPER batch (2026-07-06, all four approved by Arman): (1) `recital` — a
  performance card with NO grade bar: recite the whole passage, tap line
  numbers when stumbling (numbers only during; texts appear on the adjust
  screen), confirm; stumbled lines grade `incorrect`, the rest `hesitant`,
  junctures inherit their landing line. AttemptCreate gained optional
  `stumbled_segment_ids` (recital-only, 422 elsewhere; must be lines). The
  attempt row's own rating is incorrect-if-any-stumble. Launched manually
  (mode button), never dealt by the smart coach; the smart finisher stays
  full_passage. Known limit: the per-line stumbles feed FSRS + the mastery
  ladder but NOT `_difficult_segment_ids` (that reads per-segment Attempt
  rows; a recital is one row). (2) Juncture recall/fading prompts carry
  `audio_cue` {media_id,start,end} = the previous line's LineAligner span
  when aligned reference audio exists — "▶ Hear the cue" plays just that
  span; degrades silently to text-only. (3) `meaning_recall` — translation
  annotation as the cue, original as the answer; gates on has_translation
  like shadowing gates on audio, graduated lines only, never junctures;
  manual sessions filter to translated lines. (4) Recital confirm shows a
  pacing line ("you ≈Ns · reference ≈Ms") when every line has a cue span —
  client-side arithmetic only. Also fixed: submit_attempt now flushes before
  its remaining-items count so autoflush=False factories complete sessions.
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
- Smart exercise selection now rotates to the least-used useful mode at each
  mastery stage. Difficult segments remain first in triage but no longer receive
  `weak_link` forever: line cycles introduce random starts, forward/backward
  chaining, cue recall, and shadowing when reference audio exists. Junctures
  never receive chaining.
- Unfinished sessions expire after 24 idle hours. Expired plans and attempts are
  preserved but hidden from the default session list; stale direct links render
  an explicit expired state and cannot submit or undo attempts.
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
  "continue"): shadowing/fading recite the whole line; chaining is a recall
  card for an explicit line range inside the learned prefix; cue-recall,
  weak-link and random-start recite the line to the end; junctures recite only
  into the next line's opening (their target is the head); full-passage is start
  to finish. `random_start` is now a CHECKABLE cold start — it reuses the recall
  shape (`_recall_prompt`): a short lead-in is shown, the full line is the
  revealed answer, framed as an arbitrary drop-in entry point to break
  serial-order dependence (it was previously a full-line display with no
  reveal). The card renders it like cue_recall and it is in the reveal/Space
  allow-lists.
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
- Japanese ruby/furigana is now local dictionary support via fugashi +
  unidic-lite, not a Gemini task. Revision create/replace and prep reading
  backfills create/fill token-level `reading` ruby annotations for
  kanji-containing Japanese tokens without an API call; authored readings win
  for lyric/name overrides such as `運命` read as `さだめ`. Gemini remains
  prep-only for cue/gloss/translation and receives the local token boundaries
  so glosses can attach by word index. Token suggestions still reject blank
  readings if a model emits them for non-local fallback paths.
- Japanese reading view renders token children as the primary line surface, so
  furigana appears over each token and glosses sit underneath; older passages
  with only a whole-line `reading` ruby annotation still render through the
  existing fallback.
- Japanese practice cards show ruby by default too: progressive fading uses
  the rich token renderer on the full-support stage, and checked Japanese
  answers render ruby even when translation/gloss support layers are off.
- Japanese ruby rendering is kanji-only on the frontend even if old database
  annotations still contain kana readings: kana-only tokens render plain, and
  mixed kana/kanji tokens align the reading so okurigana stays outside `<ruby>`.
  Japanese progressive fading is token-aware in the practice card, preserving
  visible token boundaries and ruby across every non-empty stage; backend
  progressive masks now use unique quarter-step masks for spaced text and
  character fallback for no-space text so small Greek/Japanese lines do not
  duplicate stages or jump straight to blank.
- Japanese ruby/fading second pass: local UniDic output is post-processed into
  learner-facing tokens by merging auxiliaries, suffixes, connective particles,
  and non-independent verbs into the preceding content token while leaving core
  particles such as の/が separate. Generated junctures now get token children
  too, and inherit the landing line's ruby readings so context-specific song
  readings such as 水面=みなも stay consistent on "next line opening" cards.
  Progressive fading masks hidden units with dot placeholders instead of one
  collapsed ellipsis, including Greek/Latin spaced text and Japanese token
  rows.
- The dev `Sono Chi no Sadame` revision was retokenized with
  `scripts/retokenize_japanese_ruby.py`: 69 targets (35 lines + 34 junctures),
  364 token children, 203 ruby readings, zero kanji tokens missing ruby, and
  zero junctures without token children. A manual SQLite backup was written to
  `backend/data/backups/manual/rhapsode-before-japanese-retokenize-20260623.db`.
- Japanese practice rendering invariant: every Japanese target-text surface
  (shadowing, fading, chaining, cue/random/weak lead-ins, hints that match
  passage text, checked answers, and full-passage reveal) must render from
  segment token nodes when possible. The practice `reading` layer is the ruby
  switch: default on for Japanese when no saved preference exists, and respected
  as off once the user toggles it off. Raw prompt strings are a fallback only
  when no segment node/window can be matched.
- Japanese cue/juncture correction: recall lead-ins are token-based, not
  whitespace-based, so an unspaced Japanese line no longer becomes its own cue.
  Juncture heads/tails are token windows (`光と闇 …`, `… の星が`) rather than
  whole lines. The dev `Sono Chi no Sadame` DB was refreshed again: 32 junctures
  shortened, active prompt JSON updated for 3 incomplete items, 284 current
  token children, and zero kanji tokens missing ruby. A second backup is at
  `backend/data/backups/manual/rhapsode-before-japanese-cue-refresh-20260623.db`.
- Chaining is recall-first: the prompt shows only a bounded line range such as
  "lines 1-3"; the lyrics are hidden until check. Forward/backward chaining
  prompts carry chain segment ids and line-range metadata, smart planning caps
  chains at the persisted contiguous learned prefix, and grading a chain updates
  every segment in that chain. Active incomplete chaining prompts in the dev DB
  were rewritten to the corrected range payloads.
- Collections group existing passages without owning revisions. Reads and
  session launches resolve member passages' active revisions; collection
  sessions persist that revision snapshot and apply one shared smart cap or
  minutes budget across the union.
- Desktop packaging: Tauri v2 shell in `frontend/src-tauri` spawns PyInstaller
  sidecar `rhapsode-backend-<target-triple>`, sets `RHAPSODE_DESKTOP=1` and
  data paths under the OS app data dir, polls `/api/v1/health`, exposes
  `api_base_url()` to Svelte. Browser dev unchanged (Vite proxy `/api/v1`).
  CI: `.github/workflows/desktop-release.yml` builds sidecar via
  `scripts/build_backend_sidecar.py` before `tauri build`. Remote:
  `https://github.com/armantark/rhapsode.git`.

- FSRS efficiency batch (2026-07-06, Arman's ruling: stay FSRS-pure, optimize
  retention per minute of daily engagement; calendar-based ideas rejected):
  (1) Library-wide "Today" queue — SessionCreate with NO target + due_only
  spans every passage's active revision, UNCAPPED (the 12-item momentum cap is
  for exploratory smart sessions; a due queue must be clearable and FSRS
  bounds it); session row has revision_id None like collection sessions.
  Home-page banner via GET /analytics/today: due count, estimated minutes
  (same planner + latency means that build the session), streak, retention
  mirror, 7-day forecast (day 0 carries the backlog). (2) Every grade now
  persists its py-fsrs review log to `fsrs_review_logs` keyed to the attempt
  (ondelete CASCADE, PRAGMA foreign_keys=ON) so ⌘Z retracts logs — the
  optimizer never trains on undone reviews. Latency is logged only for
  single-segment attempts (fanned grades would repeat one latency). (3)
  `scripts/optimize_fsrs.py` (run with `uv run --extra optimizer`; torch
  stays out of the app/sidecar via the `optimizer` optional-dependency group)
  fits personal FSRS weights once ≥400 logs exist and writes them to the
  `fsrs_parameters` app setting; the scheduler reads them per review with
  safe fallback to defaults on absent/malformed values. (4) Streak =
  consecutive UTC days with ≥1 completed session (yesterday keeps it alive
  before the first practice of the day); desktop dock badge via the
  `set_due_badge` Tauri command (tauri 2.11 set_badge_count), invoked from
  the home page only under Tauri. Parked by ruling: hifz-style corpus
  rotation, performance-date ramp (until the Iliad class deadline hurts),
  cross-passage formula index (until ~5 same-language passages).
- Latent bug fixed with the recital batch: submit_attempt flushes before its
  remaining-items completion count (autoflush=False factories never completed
  sessions). A second latent bug shape to remember: svelte-check narrows
  $state-backed nullables to `never` inside $derived — cast via a local
  (documented in practice page and home page).

- Real-app UX pass (2026-07-06, Arman's steer: actual UX, not Tauri
  packaging): (1) launcher burrs fixed — the manual-modes <details> now binds
  its open state (the async passage load was re-rendering it shut, which was
  the "double-click" QA finding), the last manual mode selection persists in
  localStorage (`rhapsode.manualModes`) like the minutes chip, and the
  check-before-grade hint is mode-aware (typed_recall points at the button,
  not Space). (2) /settings page + nav link: Gemini key stored as the
  `gemini_api_key` app setting with env fallback (prep.resolve_api_key;
  _generate now takes an api_key param — test stubs accept it), backup health
  from GET /system/status (backup dir, newest snapshot time via
  backup.newest_snapshot_at, key configured, personal-weights active,
  retention target), sound/mic localStorage defaults surfaced. (3) Empty
  library offers "Try a sample — Iliad 1.1-5" (client-side create through the
  normal API; no backend). (4) Global "?" keyboard-shortcuts overlay in the
  layout (Esc/click-outside closes; a small ? nav button for mouse users).
  Parked from the "real app" review: cutting desktop-v0.0.2 (v0.0.1 from
  June 12 predates the entire pedagogy overhaul), signing/notarization
  (needs Arman's Apple Developer account).

## Verified Results

- Backend: 57 pytest, ruff, strict mypy, contract `--check` all green.
- Frontend: 72 vitest, svelte-check 0/0, production build green.
- Desktop: `cargo check` in `src-tauri` green; sidecar smoke
  (`scripts/desktop_sidecar_smoke.py --require-sidecar`) passes on macOS arm64.
- Session lifecycle/exercise-variety pass: 61 backend pytest, Ruff, strict mypy,
  contract check, 72 frontend tests, svelte-check, production build, and the new
  Playwright smart-rotation flow pass; the final isolated full Playwright run
  passed 12/12. Earlier navigation flakes were caused by the manual-verification
  Vite server and Playwright's Vite server concurrently regenerating the same
  `.svelte-kit` workspace. PinchTab against the real dev DB expired 4 stale
  sessions (5 active → 1 active) and verified a new Iliad smart plan containing
  random-start and forward-chaining cards.
- Japanese reading/prep pass: 66 backend pytest, Ruff, strict mypy, OpenAPI
  check, regenerated TypeScript client with no diff, 73 frontend tests,
  svelte-check, production build, 13/13 Playwright e2e, and PinchTab smoke on
  an isolated Japanese passage with token-level furigana and glosses.
- Japanese ruby repair (2026-06-23): the dev `Sono Chi no Sadame` revision was
  backfilled from 84/188 to 188/188 token ruby readings after the validator fix.
  Targeted backend prep tests pass; browser verification was left to manual QA.
- Live Gemini call drafted 5 cues + 5 glosses + 5 translations onto the real
  Iliad passage; quality checked by hand (accurate glosses, natural
  translations).
- Junctures backfilled onto the practiced Iliad revision (+4) via
  `scripts/backfill_junctures.py`; Chamberlain's CC-BY recitation of Iliad
  1.1-100 imported as reference audio via `scripts/import_reference_audio.py`.

## Next Work

- Push repo to GitHub and cut first desktop release tag (`desktop-v0.0.1` or
  `v0.0.1`) to trigger draft release workflow.
- Code signing / notarization (macOS) and Windows Authenticode — optional second
  pass; unsigned artifacts show OS trust warnings.
- Manual install smoke: open `.dmg`/installer, create passage, practice, reload,
  resume.
- Point `RHAPSODE_BACKUP_DIR` at an iCloud-synced path in the launch command.
- LLM-assisted chunking for prose passages is deferred until a prose passage
  exists (grill B4/C1).
- Parked: curated recorded SFX (synth tones are zero-dependency and graded).
