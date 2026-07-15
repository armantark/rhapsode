# System Patterns

- Contract-first API under `/api/v1`; frontend consumes generated OpenAPI.
- SQLAlchemy models are persistence details; Pydantic schemas are public types.
- Practiced passage revisions are immutable. Editing creates a new revision.
- Personal notes are mutable one-to-one overlays keyed by segment id. They stay
  outside immutable revision reads; practice hint resolution prefers the note
  over the revision-owned cue without rewriting either the revision or cue.
- All mutation endpoints accept `Idempotency-Key` and replay stored responses.
- Service functions own domain behavior; API routers translate HTTP concerns.
- Session plans and prompt items are persisted for restart-safe practice.
- Acquisition is criterion-based rather than attempt-based:
  `ReviewState.acquisition_succeeded` decides whether a target is still new.
  Generated same-session acquisition retries are append-only practice items
  with internal source provenance; the field is intentionally absent from the
  API schema so exact undo remains a persistence concern. The first smart turn
  after successful acquisition keys off both the preceding mode and rating:
  Good requests cue recall, while Easy may build forward flow when learned
  predecessor context exists; subsequent turns use the normal varied cycle.
- Source references are optional display metadata on revisions and segments.
  They never replace local ordinals, which remain the stable keys for chaining,
  junctures, appends, and review history. Chaining copy prefers complete source
  references; otherwise it explicitly scopes ordinals "in this passage."
- Active sessions are resumable for 24 idle hours. Backend lifecycle checks
  move older unfinished sessions to `expired`; normal session listings omit
  them, while direct reads preserve their plan and attempts for history.
- Smart planning separates target triage from exercise selection. Weak segments
  still receive priority, but each line receives the least-used useful exercise
  for its mastery stage so weak-link/cue drills do not crowd out chaining,
  random starts, or reference-audio shadowing. Junctures retain a narrower
  transition-focused exercise set.
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
- Collections own ordered passage memberships, while rollups and practice plans
  always resolve each member's current active revision. Collection session plans
  persist the selected revision ids and every practice item carries its revision
  id, so later passage edits cannot change the meaning of an in-flight session.
- Collection rollup queues are mutually exclusive: never-reviewed/default-grain
  segments are new, acquisition-stage segments are learning, and graduated
  segments whose review state is due now are due.
