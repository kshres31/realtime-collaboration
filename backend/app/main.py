import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import ot

MAX_DOC_LEN = 1_000_000  # UTF-16 units


class DocIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


async def commit_op(pool, doc_id: str, base: int, op: list[dict], author: str):
    """Transform op against everything committed after `base`, apply it and store it.
    The row lock serialises writers across all backend instances."""
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow("SELECT content, version FROM documents WHERE id=$1 FOR UPDATE", doc_id)
        if row is None:
            raise ValueError("document not found")
        if not 0 <= base <= row["version"]:
            raise ValueError("bad base version")
        for r in await conn.fetch(
            "SELECT op FROM operations WHERE document_id=$1 AND version>$2 ORDER BY version", doc_id, base
        ):
            op, _ = ot.transform(op, json.loads(r["op"]))
        content = ot.apply(row["content"], op)
        if ot.u16len(content) > MAX_DOC_LEN:
            raise ValueError("document too large")
        version = row["version"] + 1
        await conn.execute(
            "INSERT INTO operations (document_id, version, op, author) VALUES ($1,$2,$3,$4)",
            doc_id, version, json.dumps(op), author,
        )
        await conn.execute(
            "UPDATE documents SET content=$2, version=$3, updated_at=now() WHERE id=$1", doc_id, content, version
        )
    return op, version


def validate_op(op) -> list[dict]:
    if not isinstance(op, list) or len(op) > 100:
        raise ValueError("op must be a list of at most 100 components")
    out = []
    for c in op:
        if not isinstance(c, dict) or not isinstance(c.get("pos"), int):
            raise ValueError("bad component")
        if c.get("type") == "insert" and isinstance(c.get("text"), str) and c["text"]:
            out.append({"type": "insert", "pos": c["pos"], "text": c["text"]})
        elif c.get("type") == "delete" and isinstance(c.get("len"), int) and c["len"] > 0:
            out.append({"type": "delete", "pos": c["pos"], "len": c["len"]})
        else:
            raise ValueError("bad component")
    return out


class Hub:
    """WebSockets connected to this instance, fed by a Redis pattern subscription
    so messages published by any instance reach every client."""

    def __init__(self, redis):
        self.redis = redis
        self.local: dict[str, set[WebSocket]] = {}

    async def subscribe(self):
        self.pubsub = self.redis.pubsub()
        await self.pubsub.psubscribe("doc:*")

    async def run(self):
        pubsub = self.pubsub
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "pmessage":
                    continue
                doc_id = msg["channel"].split(":", 1)[1]
                for ws in list(self.local.get(doc_id, ())):
                    try:
                        await ws.send_text(msg["data"])
                    except Exception:
                        self.local.get(doc_id, set()).discard(ws)
        finally:
            await pubsub.aclose()

    async def publish(self, doc_id: str, payload: dict):
        await self.redis.publish(f"doc:{doc_id}", json.dumps(payload))


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = await asyncpg.create_pool(
            os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/collab")
        )
        async with app.state.pool.acquire() as conn:
            # advisory lock so concurrently starting instances don't race on CREATE TABLE
            await conn.execute("SELECT pg_advisory_lock(42)")
            await conn.execute((Path(__file__).parent / "schema.sql").read_text())
            await conn.execute("SELECT pg_advisory_unlock(42)")
        app.state.redis = aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True
        )
        app.state.hub = Hub(app.state.redis)
        await app.state.hub.subscribe()  # before serving, so no early publish is missed
        task = asyncio.create_task(app.state.hub.run())
        yield
        task.cancel()
        await app.state.redis.aclose()
        await app.state.pool.close()

    app = FastAPI(title="Realtime Collaboration", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/documents", status_code=201)
    async def create_document(body: DocIn):
        row = await app.state.pool.fetchrow(
            "INSERT INTO documents (title) VALUES ($1) RETURNING id, title, content, version", body.title
        )
        return {**row, "id": str(row["id"])}

    @app.get("/documents")
    async def list_documents():
        rows = await app.state.pool.fetch(
            "SELECT id, title, version, updated_at FROM documents ORDER BY updated_at DESC LIMIT 100"
        )
        return [{**r, "id": str(r["id"])} for r in rows]

    def parse_id(doc_id: str) -> str:
        try:
            return str(uuid.UUID(doc_id))
        except ValueError:
            raise HTTPException(404, "document not found")

    @app.get("/documents/{doc_id}")
    async def get_document(doc_id: str):
        row = await app.state.pool.fetchrow(
            "SELECT id, title, content, version FROM documents WHERE id=$1", parse_id(doc_id)
        )
        if row is None:
            raise HTTPException(404, "document not found")
        return {**row, "id": str(row["id"])}

    @app.websocket("/ws/documents/{doc_id}")
    async def document_socket(ws: WebSocket, doc_id: str, name: str = "anonymous"):
        try:
            doc_id = str(uuid.UUID(doc_id))
        except ValueError:
            await ws.close(code=4404)
            return
        name = name.strip()[:40] or "anonymous"
        hub, pool, redis = app.state.hub, app.state.pool, app.state.redis
        await ws.accept()
        # register before reading the snapshot so no op committed in between is missed;
        # clients drop ops with version <= the snapshot version
        hub.local.setdefault(doc_id, set()).add(ws)
        conn_id = uuid.uuid4().hex
        presence_key = f"presence:{doc_id}"
        try:
            row = await pool.fetchrow("SELECT title, content, version FROM documents WHERE id=$1", doc_id)
            if row is None:
                await ws.close(code=4404)
                return
            # shortcut: presence entries of a crashed instance linger until the doc is reopened; add TTL heartbeats for production
            await redis.hset(presence_key, conn_id, name)
            await hub.publish(doc_id, {"type": "join", "id": conn_id, "name": name})
            await ws.send_json({
                "type": "snapshot", "title": row["title"], "content": row["content"],
                "version": row["version"], "you": conn_id, "users": await redis.hgetall(presence_key),
            })
            while True:
                msg = await ws.receive_json()
                if msg.get("type") != "op":
                    continue
                try:
                    op, version = await commit_op(
                        pool, doc_id, int(msg.get("version", -1)), validate_op(msg.get("op")), name
                    )
                except (ValueError, TypeError) as e:
                    await ws.send_json({"type": "error", "message": str(e), "client_op_id": msg.get("client_op_id")})
                    continue
                await hub.publish(doc_id, {
                    "type": "op", "op": op, "version": version, "author": name,
                    "conn": conn_id, "client_op_id": msg.get("client_op_id"),
                })
        except WebSocketDisconnect:
            pass
        finally:
            hub.local.get(doc_id, set()).discard(ws)

            async def leave():
                await redis.hdel(presence_key, conn_id)
                await hub.publish(doc_id, {"type": "leave", "id": conn_id})

            # shielded: the server may cancel this handler on disconnect, and the leave must still go out
            await asyncio.shield(asyncio.ensure_future(leave()))

    return app


app = create_app()
