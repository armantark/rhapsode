Implement inline personal-note authoring on the Rhapsode practice card.

Read every file in `memory-bank/` first, especially
`memory-bank/handoffs/backend-to-frontend.md`. Use `contracts/openapi.json` as
the source of truth and regenerate the frontend API types before implementation.
Do not change backend schemas, LLM behavior, scheduling, or grading.

Build:

- Generated client methods and types for
  `GET/PUT /api/v1/segments/{segment_id}/note`.
- A compact inline "edit note" interaction on the practice card for the current
  segment. It must work after a revision is practiced and save through the PUT
  endpoint with an idempotency key.
- Hint precedence on the card: latest fetched personal note first, then the
  persisted `PracticeItem.prompt.hint` drafted-cue fallback.
- Treat GET `404` as "no personal note", not an error state. After a successful
  PUT, show the saved note immediately without recreating the session.

Keep the hint behind the existing "Need a hint?" reveal so recall integrity is
unchanged. Add useful frontend unit, integration, and Playwright end-to-end
coverage, then manually verify create/update/reload behavior with PinchTab.
Leave any backend contract issue in `memory-bank/handoffs/frontend-to-backend.md`.
