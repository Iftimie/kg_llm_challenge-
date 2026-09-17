"""FastAPI endpoint tests using Starlette's TestClient (in-process, no network).

``app.config.ANSWERER`` is read by the factory on every call, so monkeypatching
it is enough to force the offline ``stub`` answerer.
"""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.backend.app import app

client = TestClient(app)


def test_health_ok_and_has_answerer_key():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "answerer" in body


def test_chat_uses_stub_answerer(monkeypatch, auth_headers):
    monkeypatch.setattr(config, "ANSWERER", "stub")

    response = client.post("/api/chat", json={"message": "ping"}, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "stub answer to: ping"
    assert body["meta"]["engine"] == "stub"


@pytest.mark.parametrize("message", ["", "   ", "\n"])
def test_chat_empty_message_is_400(message, auth_headers):
    response = client.post("/api/chat", json={"message": message}, headers=auth_headers)
    assert response.status_code == 400


def test_transcript_endpoint_known(auth_headers):
    response = client.get("/api/transcripts/T007", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["deal_id"] == "D007"


def test_transcript_endpoint_unknown_is_404(auth_headers):
    response = client.get("/api/transcripts/NOPE", headers=auth_headers)
    assert response.status_code == 404


def _fresh_engine(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from app.db import engine as db_engine
    from app.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_engine, "get_engine", lambda: engine)
    return engine


def test_login_sets_cookie(monkeypatch):
    _fresh_engine(monkeypatch)
    client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "sales_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert response.cookies.get("sales_token") is not None


def test_logout_clears_cookie(monkeypatch):
    _fresh_engine(monkeypatch)
    client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    set_cookie = response.headers.get("set-cookie", "")
    assert "sales_token=" in set_cookie
    assert "Max-Age=0" in set_cookie


def test_clear_chats_deletes_history(monkeypatch, auth_headers):
    monkeypatch.setattr(config, "ANSWERER", "stub")

    client.post("/api/chat", json={"message": "ping"}, headers=auth_headers)
    listed = client.get("/api/chats", headers=auth_headers).json()
    assert len(listed["chats"]) == 1

    cleared = client.delete("/api/chats", headers=auth_headers)

    assert cleared.status_code == 200
    assert cleared.json() == {"cleared": 1}
    assert client.get("/api/chats", headers=auth_headers).json()["chats"] == []


def test_clear_chats_requires_auth():
    response = client.delete("/api/chats")
    assert response.status_code == 401


def test_list_jobs_has_status_and_created_at(auth_headers):
    client.post("/api/ingest/clear", headers=auth_headers)

    jobs = client.get("/api/jobs", headers=auth_headers).json()["jobs"]

    assert len(jobs) == 1
    assert jobs[0]["kind"] == "clear_kg"
    assert jobs[0]["status"] == "queued"
    assert "created_at" in jobs[0]
    assert "id" in jobs[0]
