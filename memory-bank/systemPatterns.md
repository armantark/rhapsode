# System Patterns

- Contract-first API under `/api/v1`; frontend consumes generated OpenAPI.
- SQLAlchemy models are persistence details; Pydantic schemas are public types.
- Practiced passage revisions are immutable. Editing creates a new revision.
- All mutation endpoints accept `Idempotency-Key` and replay stored responses.
- Service functions own domain behavior; API routers translate HTTP concerns.
- Session plans and prompt items are persisted for restart-safe practice.
- FSRS is wrapped by a scheduling service so library details do not leak.
- Language and practice extensions use validated manifests and registries.
- Python extensions can register through `rhapsode.language_plugins` and
  `rhapsode.speech_providers` entry-point groups; practice renderers share a
  stable `mode_id` with backend prompt builders.
- Media writes use temporary files followed by atomic rename.
- Media metadata is backend-discoverable; cue points are stored as validated,
  time-sorted JSON on the media asset.
- Collection endpoints that can grow substantially return explicit limit/offset
  page metadata; due reviews remain a separate scheduling query.
