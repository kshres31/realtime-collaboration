# Project status

## Done (tested)
- Backend: document REST API, WebSocket editing with server-side OT, Postgres persistence with full op history, Redis pub/sub fan-out across API instances, presence (join/leave).
- Frontend: document list and create, live editor with in-flight/buffered ops, out-of-order delivery handling, caret preservation, presence chips, auto reconnect.
- Tests: backend 8 (randomized OT convergence, REST, concurrent WebSocket edits, two app instances via Redis); frontend 3 (OT convergence, diff/caret, three simulated clients with random latency). Two real browsers on two API instances were checked to converge with Playwright.
- Docker Compose (Postgres, Redis, two API instances, web) and GitHub Actions CI (backend tests, frontend test/typecheck/build, Docker image build).

## Known limits
- No accounts or auth: anyone with the link can edit, names are self-chosen.
- Unacknowledged edits are dropped if the connection drops (the editor reloads the snapshot).
- Presence entries from a crashed API instance linger until cleared; no TTL heartbeat yet.
- Op history is never compacted.
- Plain text only (no rich text, no remote cursors).

## Possible next steps
- Auth (JWT) and per-document sharing.
- Replay unacknowledged edits after reconnect.
- Remote cursor positions and presence heartbeats.
