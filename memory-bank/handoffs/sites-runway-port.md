# Handoff: Port the Linear Runway to the GPT Sites Deployment

## Goal

The deployed Sites instance must run the same linear runway scheduler as the
local Python backend at commit `568c7e8`. The deployment must keep all
progress data that is already in the live D1 database.

## Context

- Repository root: `/Users/ArmanTarkhanian1/Documents/Codex/2026-06-10/files-mentioned-by-the-user-i`.
- The Python backend is the reference for behavior. Read these files first:
  - `backend/src/rhapsode/services/planning.py` — the runway planner
    (`build_smart_plan_for_revisions`).
  - `backend/src/rhapsode/services/sessions.py` — prompt rebuild at deal time.
  - `backend/src/rhapsode/schemas.py` — `ReviewStateRead` and
    `SystemStatusRead` contract changes.
  - `backend/tests/test_domain.py` — the runway tests. They define the exact
    expected plans.
  - `frontend/e2e/linear-runway.spec.ts` — the end-to-end contract.
- `site/` packages the app for Sites. It contains a Worker that reimplements
  the `/api/v1` contract on D1, plus a prebuilt copy of the Svelte SPA under
  `site/spa/`. `npm run build` produces `dist/`. Tests are
  `site/tests/*.test.mjs`.
- The Worker still runs the OLD scheduler: triage ranks, the new-unit
  trickle, and automatic `random_start`. The port removes them.
- The owner publishes `dist/` through their own Sites flow. There is no
  deploy script in the repository.

## Scope and non-goals

- Change only `site/`. Do not change `backend/`, `frontend/src/`, or
  `contracts/`.
- Do not add D1 schema columns. The runway reads only fields that already
  exist (`acquisition_succeeded`, `learning_step`, app settings).
- Do not run `npm run data:export`. Do not add or apply any data migration.
  The live D1 progress is the source of truth on the site, and an export from
  local SQLite would overwrite it. The deployment is code-only.
- Do not port Gemini prep. It stays a `503` on the Worker.

## Required behavior (must match the Python reference exactly)

1. A segment is mastered when `acquisition_succeeded` is true and
   `learning_step` is null.
2. `linear_window` is an app setting: an integer from 1 to 3, default 3.
   `GET /api/v1/system/status` returns it. `PUT /api/v1/settings/linear_window`
   accepts `{"value": <integer>}` and returns 422 for booleans, non-integers,
   and values outside 1–3.
3. A smart plan is one pass in passage order, in four parts:
   a. Due mastered lines and junctures. Dueness decides membership. Passage
      position decides order. A juncture is skipped when either flanking line
      is past the lock boundary.
   b. Window blocks. The active window is the first W non-mastered lines
      across the given revisions in order. A line that is not acquired gets
      one `acquisition` card. An acquired line gets three consecutive
      `guided_recall` cards. Due-only sessions deal one card per unit instead.
   c. Learning junctures whose two flanking lines are both mastered.
      A juncture that already has a review row stays schedulable.
   d. A finisher in every session: `forward_chaining` over a mastered prefix
      of two or more lines, credited to the NEWEST prefix line. When every
      line is mastered, the finisher is `full_passage`, credited to the first
      line. The 12-item cap reserves a slot for the finisher. The Today queue
      uses no cap.
4. Lines past the window boundary are never dealt, in any path, including
   minutes fills. Minutes fills exempt `acquisition` and `guided_recall`
   material. No automatic path deals `random_start`; manual sessions keep it.
   Triage ranks and the new-unit trickle are removed.
5. `guided_recall` and acquisition-retry prompts are rebuilt from the current
   review state each time a session is read. Repeated cards in one session
   show the advanced cue level. Undo restores the matching prompt state.
6. `ReviewStateRead` includes `acquisition_succeeded` and `learning_step`.
7. The Today `due_count` counts only due units that the runway will deal.

## Steps

1. Read the reference files listed in Context.
2. Port behaviors 1–7 to the Worker planner and session routes in `site/`.
3. Add Worker tests that mirror the runway tests in
   `backend/tests/test_domain.py`: window gate, lock, blocks, juncture gate,
   finisher credit, cap reservation, deal-time rebuild, no `random_start`,
   and the `linear_window` setting round trip.
4. Rebuild the SPA copy from the current frontend build and refresh
   `site/spa/` with it. The new SPA reads `system_status.linear_window` and
   the two new `ReviewStateRead` fields. The Worker must serve them, or the
   passage page breaks.
5. Run `npm run build` and `npm test` in `site/`. Fix failures.
6. Publish `dist/` with the usual Sites flow. Do not publish any data
   migration.
7. After publish, open the live site. Confirm: the passage page shows the
   runway strip, a smart session deals in passage order, and the D1 progress
   from before the deploy is still present.

## Verification

- `cd site && npm run build && npm test` — all tests pass.
- Live smoke after publish: runway strip visible, session order is linear,
  old progress intact, `PUT /settings/linear_window` with value 1 returns 200
  and with value 4 returns 422.

## Report

Return: the list of changed files, the test counts, the publish result with
the live URL, and any behavior you could not match exactly with the reason.

## Addendum (2026-07-28): warmup → work → cooldown

The local backend changed again after the first Sites deploy, at commit
`568c7e8`'s successor. Port these changes with the same rules as above:

1. Chains left every automatic rotation. `forward_chaining` and
   `backward_chaining` are no longer valid outputs of the review-mode
   rotation or the minutes-fill cycle, for lines or junctures. Both stay
   available as manual modes. In manual plans, `backward_chaining` chains
   from each start line to the end of the passage.
2. Every smart session opens with one warmup card before the due reviews:
   a `forward_chaining` card over the last three (or fewer) lines of the
   mastered prefix. The prefix tail comes from the LAST collection member
   that has a mastered prefix, because a chain cannot span revisions. When
   the tail is a single line, the warmup is one `cue_recall` card instead —
   unless the review portion already deals that line, in which case there is
   no warmup card.
3. The warmup reserves one slot inside the 12-item cap, exactly like the
   finisher. Under a minutes budget, the warmup cost is subtracted first.
4. The graduated review rotation is now `typed_recall` and `cue_recall`
   only. The learning rotation is `word_bank`, `cue_recall`, and
   `progressive_fading`. The first return after a successful acquisition
   always deals `cue_recall`.
5. The reference tests changed with the behavior. Re-read
   `backend/tests/test_domain.py` (warmup, rotation, and fill tests) and
   `frontend/e2e/linear-runway.spec.ts` (the `masterLine` helper now reads
   mastery from `/api/v1/analytics/due` fields, not from card absence).

The reason, for context in code comments: dueness decides review
membership, so when only the newest lines were due, "reviews first" meant
"hardest first", and the rotation could open a session with a cold
multi-line chain ("recite Iliad 1.8 through 1.10") that had no lead-in.

## Risks and open questions

- Warning: `npm run data:export` overwrites the live data migration from
  local SQLite. Do not run it. The two databases stay separate until the
  owner decides a sync direction.
- The prebuilt SPA copy must come from the same commit as the Worker port
  (`568c7e8` or later). A mismatch breaks the passage page.
