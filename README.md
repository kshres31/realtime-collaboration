# Realtime Collaboration

Google-Docs-style collaborative text editing. Several people edit the same document at once, every keystroke shows up for everyone else within milliseconds, and concurrent edits merge without anyone's text being lost.

**Stack:** Python / FastAPI (WebSockets), PostgreSQL, Redis pub/sub, TypeScript / React / Next.js, Docker, GitHub Actions.

## How it works

```
 browser ──ws──▶ api (FastAPI) ──┐                ┌──▶ api2 ──ws──▶ browser
                    │            ├── Redis pub/sub ┤
                    └── Postgres (documents, ops, row lock per document)
```

- **Operational transform (OT).** Every edit is an op: a list of `insert(pos, text)` / `delete(pos, len)` components, sent with the document version it was based on. The server locks the document row (`SELECT … FOR UPDATE`), transforms the op past every op committed since that version, applies it, stores it in an append-only `operations` table and bumps the version. The row lock makes this correct even with many API instances.
- **Fan-out across instances.** After commit, the op is published on Redis channel `doc:<id>`. Each API instance holds a pattern subscription and forwards to its own WebSocket clients, so two people on different instances see each other's edits (tested).
- **Client.** `frontend/lib/session.ts` keeps one op in flight and buffers later keystrokes, transforms incoming remote ops past both, applies ops strictly in version order (messages from different instances can arrive out of order), and keeps the caret in place when remote text shifts it.
- **Presence.** Who is in a document lives in a Redis hash, with join/leave events over the same channel.
- Positions count UTF-16 code units on both sides so emoji and other non-BMP text line up between Python and JavaScript.

The OT functions exist in both Python (`backend/app/ot.py`) and TypeScript (`frontend/lib/ot.ts`) and both are checked by the same randomized convergence property.

## Run it

```bash
docker compose up --build
```

Open http://localhost:3000 in two windows. A second API instance runs on port 8001 to show cross-instance sync.

### Development

```bash
# backend (needs Postgres and Redis running locally)
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
createdb collab_test && pytest -q
DATABASE_URL=postgresql://postgres@localhost/collab uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm test && npm run dev
```

## API

| Method | Path | |
|---|---|---|
| `POST` | `/documents` | create `{title}` |
| `GET` | `/documents` | list |
| `GET` | `/documents/{id}` | content and version |
| `WS` | `/ws/documents/{id}?name=…` | live editing session |

WebSocket messages: server sends `snapshot`, `op`, `join`, `leave`, `error`; client sends `{"type":"op","version":n,"op":[…],"client_op_id":"…"}`.
