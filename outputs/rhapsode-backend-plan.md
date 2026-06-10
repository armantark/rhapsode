# Rhapsode Backend Implementation Plan

## Goal

Build the local-first Python backend for Rhapsode, a modular oral memorization
platform. The backend owns passage structure, immutable revisions, annotations,
media metadata, guided practice plans, resumable sessions, attempts, FSRS
scheduling, analytics, plugins, settings, and the versioned API contract.

## Stack

- Python 3.13 managed with `uv`
- FastAPI and Pydantic v2
- SQLAlchemy 2 and Alembic
- SQLite in WAL mode
- Py-FSRS
- Local filesystem media storage
- Pytest, Ruff, and mypy

## Delivery Sequence

1. Establish repository, memory bank, API conventions, and project tooling.
2. Implement persistence models and initial Alembic migration.
3. Implement language profiles, passages, immutable revisions, annotations,
   media, plugins, sessions, attempts, scheduling, analytics, and settings.
4. Expose the behavior under `/api/v1` with idempotency on mutations.
5. Generate `contracts/openapi.json` and multilingual fixture bundles.
6. Verify unit, integration, contract, restart-recovery, and end-to-end flows.
7. Leave a decision-complete frontend handoff without creating frontend code.

## Product Boundaries

- Single-user and bound to `127.0.0.1`; no authentication or cloud services.
- Manual or imported segmentation and annotations; no automatic NLP.
- Uploaded trusted reference audio and explicitly saved best attempts persist.
- Speech scoring is represented only as a disabled extension point.
- Language profiles are declarative; optional Python plugins can extend them.
- Practice modes are plugin-capable, with a complete built-in oral suite.

## Backend Acceptance Criteria

- Passages can be created, revised, segmented, annotated, and practiced.
- Practiced revisions cannot be mutated; editing creates a new revision.
- Guided sessions persist across process restarts.
- Attempts update FSRS state and due dates through four oral-recall ratings.
- Weak-link analytics and due reviews are queryable.
- Media uploads are atomic and enforce allowed persistence categories.
- Every mutation accepts and replays an idempotency key.
- The committed OpenAPI contract matches the running application.
- Ruff, mypy, and the full pytest suite pass.

