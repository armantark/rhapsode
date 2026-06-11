Implement the Rhapsode frontend collection/deck tree and collection practice launcher.

Read every file in `memory-bank/` first, especially
`memory-bank/handoffs/backend-to-frontend.md`. Use `contracts/openapi.json` as
the source of truth and regenerate the frontend API types before implementation.
Do not change backend schemas or behavior.

Build:

- A collection/deck tree that lists `CollectionRead.members` in saved position
  order and shows the `{ due, learning, new }` rollup.
- Collection create, rename, delete, add passage, remove passage, and reorder
  interactions using the documented `/api/v1/collections` endpoints.
- A practice launcher that can target either one passage revision or one
  collection. Send exactly one of `revision_id` or `collection_id` to
  `POST /api/v1/sessions`, preserving the existing mode, kind, due-only, and
  minutes controls.
- Collection-session practice context using each `PracticeItemRead.revision_id`
  so passage-specific labels/media remain correct while moving across members.

Keep mutations idempotent. Add useful frontend unit, integration, and
Playwright end-to-end tests, then manually verify the collection workflow with
Pinchtab. Leave any backend contract issue in
`memory-bank/handoffs/frontend-to-backend.md`.
