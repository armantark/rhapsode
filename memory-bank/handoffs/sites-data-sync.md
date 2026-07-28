# Handoff: Sites Data Sync and Second Deploy

## Role

You are the Codex session with access to the deployed Sites instance
(`rhapsode-arman.tarkavor.chatgpt.site`) and its D1 database. The repository
is `/Users/ArmanTarkhanian1/Documents/Codex/2026-06-10/files-mentioned-by-the-user-i`.
Claude handles all local-database work; you handle the Sites side.

## Goal

Make the deployed site run the current scheduler on one merged Iliad passage,
with no loss of the practice progress that lives in D1 today. The sync
direction is decided: D1 progress comes down first, the merge happens
locally, and the merged database goes back up. This document covers your two
phases. Phase B must not start before the owner says "go".

## Phase A — export the live D1 data (do this now)

Outcome: a complete, self-describing export of every D1 table, written to
`work/d1-export/` in the repository, plus a short report.

- Include every table and every row. Learning history is the point:
  review states, attempts, FSRS review logs, sessions, practice items,
  personal notes, settings, passages, revisions, segments, annotations,
  collections, media metadata.
- The format must be machine-readable without guesses: SQL inserts or JSON
  per table, with column names stated. Note anywhere the D1 schema differs
  from the backend SQLite schema in `backend/src/rhapsode/models.py`.
- Phase A is read-only. Do not change D1, do not deploy, do not run
  `npm run data:export`.
- Success means Claude can rebuild the exact D1 state locally from your
  files alone.

Warn the owner in your report: from the moment of this export until the
Phase B deploy, practice on the deployed site is lost work. Practice locally
in that window.

## Phase B — port, repackage, deploy (only after the owner says "go")

By then the local database is the merged source of truth: one Iliad passage,
D1 progress imported, runway scheduler with the warmup shape.

Outcome: the deployed site runs the same behavior and data.

- Port the Worker scheduler per
  `memory-bank/handoffs/sites-runway-port.md`, including its 2026-07-28
  addendum (warmup → work → cooldown). The Python planner in
  `backend/src/rhapsode/services/planning.py` is the reference; the backend
  tests define the expected plans.
- Refresh the SPA copy in `site/spa/` from the current frontend build. The
  SPA and the Worker must come from the same commit.
- Regenerate the data migration with `npm run data:export`. This is now the
  intended one-way sync from the merged local database. This is the only
  point in the whole plan where that command is allowed.
- Success means: `cd site && npm run build && npm test` pass; after deploy,
  the live site shows ONE Iliad passage with the runway strip and the full
  merged progress; a smart session opens with a warmup chain and never deals
  `random_start`; the old split Iliad passages are absent or clearly marked
  merged.

## Phase A amendment (2026-07-28): export through the Worker

Phase A was blocked as reported: the Sites connector has no raw D1 surface,
and no Cloudflare credentials exist. The unblock uses the access you have.
A code-only deploy is now allowed in Phase A, with this exact scope:

- Add one temporary Worker route, `GET /api/v1/admin/export`, that returns
  every D1 table verbatim as JSON: the `sqlite_master` schema plus
  `SELECT *` per table, including `fsrs_card_json` and the FSRS review
  logs. The route must require a long random token that you generate and
  bake into the build; without the token it returns 404. Print the token
  only in your local report, never in logs or commits.
- The deploy must change code only. Do not run `npm run data:export`. Before
  you deploy, confirm the bundled D1 migrations are identical to the ones
  already applied to the live database, and confirm from the platform's
  status output that the deploy will not re-apply data migrations. If you
  cannot confirm either, stop and report.
- After the deploy, fetch the export to `work/d1-export/` (uncommitted; it
  is personal learning history), verify row counts against the live app's
  visible state, and report. The practice freeze begins at the moment the
  fetch succeeds.
- Removal of the export route is part of the Phase B deploy.

## Stop rules

- If D1 access or the export tooling is unavailable, stop and report exactly
  what access is missing. Do not reconstruct data from the SPA or by
  scraping.
- If the D1 schema does not match the backend schema and the difference
  affects learning data, export the raw truth, document the difference, and
  let Claude resolve it on import. Do not transform data yourself.
- If a Phase B test or the live smoke fails, report the failure. Do not
  ship a partial deploy.
- Ask the owner only when a decision changes data or scope; otherwise
  proceed within the phase you are in.

## Report

Each phase ends with: the file list you produced, row counts per table
(Phase A) or test counts and the live URL (Phase B), and any schema
difference or blocker found.
