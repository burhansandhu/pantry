"""Run against a disposable database locally or the PostgreSQL CI service."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from test_api import answer, events, start

from backend.main import create_app

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL, reason="TEST_DATABASE_URL is not configured"
)


@pytest.fixture
def database():
    # Use only a disposable test database, never the application's production DB.
    with connect(DB_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS pantry_sessions, pantry_rate_limits")
    return DB_URL


def test_review_and_recipe_survive_instance_changes(fake_provider, database):
    with TestClient(create_app(database)) as first:
        sid, review, _ = start(first)
    assert not fake_provider[0]["generation"]
    with TestClient(create_app(database)) as second:
        restored = second.get(f"/api/sessions/{sid}").json()
        assert restored["review"] == review
        assert restored["busy"] is False
        assert answer(second, sid, review, "keep").status_code == 422
        assert second.get(f"/api/sessions/{sid}").json()["busy"] is False
        result = events(answer(second, sid, review, "generate"))
        assert result[-1]["type"] == "done"
    with TestClient(create_app(database)) as third:
        assert (
            third.get(f"/api/sessions/{sid}").json()["recipe"] == result[-1]["recipe"]
        )
        assert answer(third, sid, review, "generate").status_code == 409
    assert len(fake_provider[0]["generation"]) == 1


def test_shared_busy_lease_and_expired_request(fake_provider, database):
    with (
        TestClient(create_app(database)) as first,
        TestClient(create_app(database)) as second,
    ):
        sid, review, _ = start(first)
        with connect(database, autocommit=True) as conn:
            conn.execute(
                "UPDATE pantry_sessions SET processing_until = now() + interval '4 minutes', lease = %s WHERE id = %s",
                (str(uuid4()), sid),
            )
        assert answer(second, sid, review, "generate").status_code == 409
        with connect(database, autocommit=True) as conn:
            conn.execute(
                "UPDATE pantry_sessions SET processing_until = now() - interval '1 second' WHERE id = %s",
                (sid,),
            )
        state = second.get(f"/api/sessions/{sid}").json()
        assert state["busy"] is False
        assert "interrupted" in state["error"].lower()
        assert answer(second, sid, review, "generate").status_code == 409
        assert not fake_provider[0]["generation"]


def test_shared_rate_limit_and_session_expiry(fake_provider, database, monkeypatch):
    monkeypatch.setenv("RECIPE_STARTS_PER_HOUR", "1")
    with TestClient(create_app(database)) as first:
        sid, _, _ = start(first)
    with TestClient(create_app(database)) as second:
        assert (
            second.post("/api/sessions", json={"ingredients": ["rice"]}).status_code
            == 429
        )
        with connect(database, autocommit=True) as conn:
            conn.execute(
                "UPDATE pantry_sessions SET touched = now() - interval '7 hours' WHERE id = %s",
                (sid,),
            )
        assert second.get(f"/api/sessions/{sid}").status_code == 404
