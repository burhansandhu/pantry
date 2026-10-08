import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.storage import MemoryStore, PostgresStore
from recipe_agent.errors import public_error_message
from recipe_agent.schemas import IngredientsRequest, ReviewResponse, validate_response
from recipe_agent.state import initial_state

logger = logging.getLogger(__name__)


def create_app(database_url=None):
    database_url = database_url or os.getenv("DATABASE_URL")
    local_store = MemoryStore()

    @asynccontextmanager
    async def lifespan(app):
        if not database_url:
            if os.getenv("VERCEL"):
                raise RuntimeError(
                    "Set DATABASE_URL before deploying Pantry on Vercel."
                )
            app.state.store = local_store
            yield
            return
        async with AsyncConnectionPool(
            database_url,
            min_size=0,
            max_size=5,
            timeout=15,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=False,
        ) as pool:
            store = PostgresStore(
                pool,
                AsyncPostgresSaver(pool),
                hourly_limit=int(os.getenv("RECIPE_STARTS_PER_HOUR", "30")),
            )
            await store.setup(os.getenv("DATABASE_URL_UNPOOLED") or database_url)
            app.state.store = store
            yield

    app = FastAPI(title="Pantry / Recipe Agent", version="0.1.0", lifespan=lifespan)
    app.state.sessions = local_store.sessions
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv(
            "FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(","),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def config(session_id):
        return {"configurable": {"thread_id": session_id}, "recursion_limit": 60}

    def event(data):
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def stream(session_id, session, value):
        session.error = None

        async def events():
            terminal = None
            try:
                yield event({"type": "session", "session_id": session_id})
                session.pending = None
                async with asyncio.timeout(180):
                    async for mode, chunk in session.graph.astream(
                        value, config(session_id), stream_mode=["custom", "updates"]
                    ):
                        if mode == "custom":
                            yield event(chunk)
                        elif "__interrupt__" in chunk:
                            interruption = chunk["__interrupt__"][0]
                            session.pending = interruption.value | {
                                "review_id": interruption.id
                            }
                            terminal = {"type": "review", "review": session.pending}
                snapshot = await session.graph.aget_state(config(session_id))
                if snapshot.values.get("recipe") and not snapshot.next:
                    terminal = {
                        "type": "done",
                        "recipe": snapshot.values["recipe"],
                        "ingredients": snapshot.values["ingredients"],
                    }
            except asyncio.CancelledError:
                session.error = "Connection interrupted. Start a new recipe to retry."
                raise
            except Exception as exc:
                logger.exception("Recipe session failed")
                session.error = public_error_message(exc)
                terminal = {"type": "error", "message": session.error}
            finally:
                try:
                    await asyncio.shield(app.state.store.release(session_id, session))
                except Exception:
                    logger.exception("Could not persist recipe review")
                    terminal = {
                        "type": "error",
                        "message": "Could not save this recipe session. Start a new recipe to retry.",
                    }
            # Persist the review and release its lease before the browser can
            # submit another approval to a different serverless instance.
            if terminal:
                yield event(terminal)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "provider": "groq",
            "configured": bool(os.getenv("GROQ_API_KEY")),
        }

    @app.post("/api/sessions")
    async def start(request: IngredientsRequest, http_request: Request):
        if not os.getenv("GROQ_API_KEY"):
            raise HTTPException(
                503,
                "Set GROQ_API_KEY in the backend environment and restart or redeploy.",
            )
        sid = str(uuid4())
        # Vercel overwrites this header with the actual client IP. Ignore
        # user-controlled forwarded headers on other hosting platforms.
        address = (
            http_request.headers.get("x-vercel-forwarded-for", "unknown").split(",")[0]
            if os.getenv("VERCEL")
            else (http_request.client.host if http_request.client else "unknown")
        )
        client_key = hashlib.sha256(address.encode()).hexdigest()
        session = await app.state.store.create(sid, client_key)
        return stream(
            sid,
            session,
            initial_state(
                request.ingredients,
                request.preferences,
                request.allergies,
                request.substitution_requests,
            ),
        )

    @app.get("/api/sessions/{session_id}")
    async def snapshot(session_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        session = await app.state.store.get(session_id)
        snapshot = await session.graph.aget_state(config(session_id))
        return {
            "session_id": session_id,
            "busy": session.busy,
            "review": session.pending,
            "error": session.error,
            "recipe": snapshot.values.get("recipe", ""),
            "ingredients": snapshot.values.get("ingredients", []),
            "preferences": snapshot.values.get("user_preferences", ""),
            "allergies": snapshot.values.get("allergies", []),
            "substitution_requests": snapshot.values.get("substitution_requests", []),
        }

    @app.post("/api/sessions/{session_id}/respond")
    async def respond(session_id: str, answer: ReviewResponse):
        session = await app.state.store.acquire(session_id)
        try:
            if not session.pending or session.error:
                raise HTTPException(
                    409, "There is no active review. Start a new recipe."
                )
            validate_response(answer, session.pending)
        except ValueError as exc:
            await app.state.store.release(session_id, session)
            raise HTTPException(422, str(exc)) from exc
        except HTTPException:
            await app.state.store.release(session_id, session)
            raise
        return stream(session_id, session, Command(resume=answer.model_dump()))

    return app


app = create_app()
