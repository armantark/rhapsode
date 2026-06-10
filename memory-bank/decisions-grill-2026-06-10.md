# Architecture grill session — 2026-06-10

Format: each entry is a design question, the recommendation given, Arman's
ruling, and the consequence. This is the authoritative record; implementation
should follow these rulings.

## A. Time-based smart sessions

### A1. How to convert a time budget into an item count
- **Question:** The planner needs seconds-per-item to turn "≈15 min" into a
  cap. What estimator?
- **Recommendation:** Per-mode mean from the user's own attempt history
  (`Attempt.latency_ms`), falling back to fixed per-mode defaults until ≥5
  attempts exist for that mode. Self-corrects with practice.
- **Ruling:** Accepted (option A). Raised a refinement: unfocused window time
  should probably not count toward latency — see A2.

### A2. Should the latency clock pause while the window is unfocused?
- **Question:** Arman alt-tabs a lot; raw wall-clock latency inflates both the
  time estimator and the hesitation signal in weak links.
- **Recommendation:** Pause while the window is blurred OR the tab is hidden
  (`window` blur/focus + `document` visibilitychange together) — blur catches
  alt-tab and other-browser-window switches that visibilitychange misses on
  macOS.
- **Ruling:** Accepted — pause on blur OR hidden. No outlier clamping needed
  on top.

### A3. API and UI shape of the time budget
- **Question:** How does the budget travel and appear?
- **Recommendation:** Optional `minutes` on `SessionCreate`; backend converts
  to an item cap via the A1 estimator. Absent → today's 12-item cap, so
  nothing silently changes. UI: ≈5 / ≈15 / ≈30 min chips beside the Smart
  session button, last choice remembered in localStorage. The time→items math
  lives in the backend because that's where attempt history lives.
- **Ruling:** Accepted as recommended.

### A4. Full-passage finisher vs. the budget
- **Question:** A full recitation of a long passage could eat a small budget
  alone. Does the finisher count?
- **Recommendation:** It counts (estimated from full_passage latency history),
  but when the passage is fully graduated it is budgeted FIRST and per-line
  maintenance fills the remainder — whole-flow recitation is the
  highest-value use of a mastered passage's minutes.
- **Ruling:** Accepted as recommended.

## B. Coach signals

### B1. Difficulty flag must decay
- **Question:** `_difficult_segment_ids` marks a segment difficult forever
  after a single Again/Hard attempt; it then outranks everything in triage and
  gets weak_link drilling for life.
- **Recommendation:** A segment exits difficult status after 2 consecutive
  clean attempts since its last difficult attempt — "repaired" means
  demonstrated twice without help; once could be luck.
- **Ruling:** Accepted — decay after 2 consecutive cleans.

### B2. Mastery stages must be able to regress
- **Question:** Stages are derived from LIFETIME clean counts (2 → review,
  5 → durable) and never go down, so a lapsed "durable" line keeps getting
  unsupported cold-start drills.
- **Recommendation:** Count consecutive cleans instead. Again (revealed)
  resets the streak to 0; Hard (incorrect) demotes one threshold step; Good
  (hesitant) leaves the streak unchanged. FSRS scheduling untouched — the
  ladder only selects drills.
- **Ruling:** Accepted as recommended.

### B3. Junctures (line-to-line transitions) become first-class
- **Question:** The classic oral-verse failure is between lines; nothing
  tracks it today.
- **Recommendation:** New auto-generated segment kind `juncture` (tail of
  line N as cue, head of line N+1 as target). As ordinary segments they get
  FSRS state, weak-link analytics, triage, and grading for free — no new
  tables. Must land before the big Iliad import so junctures exist from
  day one.
- **Ruling:** Accepted as recommended.

### B4. One practice grain per passage
- **Question:** Default segment_kinds ['chunk','line'] would double-deal text
  if chunks ever existed; nothing generates chunks today.
- **Recommendation:** Planner enforces one grain per passage — chunks if the
  revision has them, else lines. Chunking remains explicitly authored for
  prose, not auto-generated.
- **Ruling:** Accepted, with a rider: Arman is "quite lazy" and may never
  author chunks/cues manually — wants LLM assistance considered (see C1).

### D3. Plugin system frozen
- **Question:** Keep, freeze, or remove the plugin registry (custom practice
  modes, speech_scoring stub)?
- **Ruling:** Freeze — no new plugin surface, no removal effort. The original
  modularity goal (per-language features) is already served by language
  profiles as data. Speech scoring stays dead: automated scoring of
  reconstructed Ancient Greek pronunciation has no trustworthy ground truth;
  the human ear plus self-grading is the instrument. New capabilities (LLM
  prep, junctures) land as plain code.

## E. Execution

### E1. Sequencing
- **Question:** Recommended order was D1 → B → A → D2 → C, split
  backend/frontend per the usual two-dev workflow.
- **Ruling:** Do everything at once, both sides, in one thread — Arman
  explicitly waived the backend/frontend thread split for this batch.
- **Note:** FSRS desired_retention stays at the 0.9 default; nobody contested
  it and it matches Anki's convention.

## C. LLM assistance

### C1. Scope: preparation assistant only
- **Question:** Should an LLM enter the app, and where is the fence?
- **Recommendation:** Prep-only: drafts chunk boundaries, recall cues, and
  glosses/translations as ordinary editable segments/annotations behind a
  "suggest" button. The practice loop (planning, scheduling, grading) stays
  deterministic and offline so a network outage can never cost a session.
- **Ruling:** Accepted — prep only.

### C2. Provider: Gemini 3.1 Pro
- **Question:** Which model? (Per standing rule, the model is Arman's call
  and must not be changed without his say-so.)
- **Ruling:** Gemini 3.1 Pro — Arman judges it best at classical languages,
  especially Armenian; he has an API key. Structured output enforced via
  Pydantic-validated responses, XML-tagged prompts, no few-shot examples
  (per standing LLM rules).

## D. Data durability

### D1. Backups beyond pre-migration snapshots
- **Question:** Snapshots only happen before migrations and live on the same
  disk as the database; months of practice history sit unprotected between
  migrations.
- **Recommendation:** Snapshot on server startup when the newest snapshot is
  >24h old, retain the last 14, and point backup_dir at an iCloud-synced
  folder so machine loss isn't total loss. Startup is a quiet-db moment and
  needs no scheduler.
- **Ruling:** Accepted as recommended.

### D2. Recordings: opt-in mic, keep machinery, import reference audio
- **Question:** Arman likely won't record himself (grating to hear own
  voice); is recording even a good learning measure?
- **Assessment:** Not for retention — the production effect comes from
  speaking aloud, not from reviewing playback, and self-grades already
  capture what the scheduler needs. The valuable direction is the reverse:
  shadowing a fluent reference recitation encodes meter and pronunciation.
- **Ruling:** Keep browser-local + explicit best-take upload, but demote the
  mic to an opt-in toggle outside the default flow. Import Chamberlain's
  CC-licensed Iliad recitations as shadowing reference audio.
