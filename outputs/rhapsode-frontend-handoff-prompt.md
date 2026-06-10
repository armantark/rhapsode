# Rhapsode Frontend Handoff Prompt

Implement the Svelte frontend for Rhapsode using the backend contract and
fixtures already present in `contracts/`.

Read every file in `memory-bank/` first, especially
`memory-bank/handoffs/backend-to-frontend.md`. Do not modify backend-owned
schemas or API behavior without documenting a requested contract change.

Build a desktop-first responsive “scholarly arcade” interface for:

- Passage library and multilingual passage editor
- Hierarchical sections, lines, chunks, tokens, and configurable annotations
- Reference-audio upload, looping, cue points, and playback speed
- Guided resumable oral-practice sessions
- Browser-local ephemeral attempt recording and playback
- Four self-grading actions: clean, hesitant, incorrect, and revealed
- Mastery, due-review, weak-link, and saved-best views
- Greek, Armenian, Latin, and Japanese rendering, including ruby and vertical Japanese

Generate the TypeScript client from `contracts/openapi.json`. Develop against
the committed fixtures and backend API. Keep recording ephemeral unless the
user explicitly saves a best attempt.

Add frontend unit, integration, and end-to-end tests. Perform manual browser
testing with Pinchtab for microphone permissions, Unicode rendering, keyboard
navigation, session recovery, and responsive layouts. Leave a
frontend-to-backend handoff note for any integration issues.

