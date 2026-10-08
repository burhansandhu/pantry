"""Local sessions and shared PostgreSQL sessions with exclusive request leases."""

import time
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from psycopg.types.json import Jsonb

from recipe_agent.graph import build_graph

SESSION_TTL = 6 * 60 * 60
MAX_SESSIONS = 200
LEASE_SECONDS = 240  # Longer than the 180-second generation deadline.
INTERRUPTED = "Connection interrupted. Start a new recipe to retry."


@dataclass
class Session:
    graph: object = field(default_factory=lambda: build_graph(InMemorySaver()))
    busy: bool = False
    pending: dict | None = None
    error: str | None = None
    touched: float = field(default_factory=time.monotonic)
    lease: str | None = None


class MemoryStore:
    def __init__(self):
        self.sessions = {}

    async def create(self, session_id, client_key=None):
        for sid, old in list(self.sessions.items()):
            if not old.busy and time.monotonic() - old.touched > SESSION_TTL:
                del self.sessions[sid]
        if len(self.sessions) >= MAX_SESSIONS:
            raise HTTPException(503, "The kitchen is busy. Try again later.")
        session = self.sessions[session_id] = Session(busy=True)
        return session

    async def get(self, session_id):
        session = self.sessions.get(session_id)
        if session is None or time.monotonic() - session.touched > SESSION_TTL:
            self.sessions.pop(session_id, None)
            raise HTTPException(
                404, "Session expired or not found. Start a new recipe."
            )
        session.touched = time.monotonic()
        return session

    async def acquire(self, session_id):
        session = await self.get(session_id)
        if session.busy:
            raise HTTPException(409, "This session is already processing a request.")
        session.busy = True
        return session

    async def release(self, session_id, session):
        session.busy = False
        session.touched = time.monotonic()


class PostgresStore:
    def __init__(self, pool, checkpointer, hourly_limit=30):
        self.pool = pool
        self.checkpointer = checkpointer
        self.graph = build_graph(checkpointer)
        self.hourly_limit = hourly_limit

    async def setup(self):
        # Serialize schema initialization across cold starts. Checkpoint setup
        # uses another autocommit connection because it creates concurrent indexes.
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(731042181)")
            await self.checkpointer.setup()
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pantry_sessions (
                    id TEXT PRIMARY KEY,
                    pending JSONB,
                    error TEXT,
                    touched TIMESTAMPTZ NOT NULL DEFAULT now(),
                    processing_until TIMESTAMPTZ,
                    lease TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pantry_rate_limits (
                    client_key TEXT PRIMARY KEY,
                    starts INTEGER NOT NULL,
                    expires TIMESTAMPTZ NOT NULL
                )
            """)

    def session(self, row):
        return Session(
            graph=self.graph,
            busy=row["processing_until"] is not None,
            pending=row["pending"],
            error=row["error"],
            lease=row["lease"],
        )

    async def create(self, session_id, client_key=None):
        lease = str(uuid4())
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(731042182)")
            expired = await conn.execute(
                "DELETE FROM pantry_sessions WHERE touched < now() - %s * interval '1 second' RETURNING id",
                (SESSION_TTL,),
            )
            expired_ids = [row["id"] for row in await expired.fetchall()]
            await conn.execute("DELETE FROM pantry_rate_limits WHERE expires < now()")
            count = await conn.execute("SELECT count(*) AS count FROM pantry_sessions")
            if (await count.fetchone())["count"] >= MAX_SESSIONS:
                raise HTTPException(503, "The kitchen is busy. Try again later.")
            if client_key:
                rate = await conn.execute(
                    """INSERT INTO pantry_rate_limits VALUES (%s, 1, now() + interval '1 hour')
                       ON CONFLICT (client_key) DO UPDATE
                       SET starts = pantry_rate_limits.starts + 1 RETURNING starts""",
                    (client_key,),
                )
                if (await rate.fetchone())["starts"] > self.hourly_limit:
                    raise HTTPException(
                        429, "Recipe request limit reached. Try again in an hour."
                    )
            row = await conn.execute(
                """INSERT INTO pantry_sessions (id, processing_until, lease)
                   VALUES (%s, now() + %s * interval '1 second', %s) RETURNING *""",
                (session_id, LEASE_SECONDS, lease),
            )
            session = self.session(await row.fetchone())
        for sid in expired_ids:
            await self.checkpointer.adelete_thread(sid)
        return session

    async def get(self, session_id):
        async with self.pool.connection() as conn:
            # A killed function cannot leave the session permanently busy or
            # allow a partially processed approval to be resumed a second time.
            await conn.execute(
                """UPDATE pantry_sessions SET processing_until = NULL, lease = NULL, error = %s
                   WHERE id = %s AND processing_until < now()""",
                (INTERRUPTED, session_id),
            )
            result = await conn.execute(
                "SELECT * FROM pantry_sessions WHERE id = %s AND touched > now() - %s * interval '1 second'",
                (session_id, SESSION_TTL),
            )
            row = await result.fetchone()
            if row is None:
                raise HTTPException(
                    404, "Session expired or not found. Start a new recipe."
                )
            return self.session(row)

    async def acquire(self, session_id):
        await self.get(session_id)
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """UPDATE pantry_sessions SET processing_until = now() + %s * interval '1 second',
                   lease = %s, touched = now() WHERE id = %s AND processing_until IS NULL RETURNING *""",
                (LEASE_SECONDS, str(uuid4()), session_id),
            )
            row = await result.fetchone()
            if row is None:
                raise HTTPException(
                    409, "This session is already processing a request."
                )
            return self.session(row)

    async def release(self, session_id, session):
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """UPDATE pantry_sessions SET pending = %s, error = %s, touched = now(),
                   processing_until = NULL, lease = NULL WHERE id = %s AND lease = %s""",
                (Jsonb(session.pending), session.error, session_id, session.lease),
            )
            if result.rowcount != 1:
                raise RuntimeError("Session request lease was lost")
        session.busy = False
