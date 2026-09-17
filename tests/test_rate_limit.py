"""Rate-limiting tests (in-memory, per-user chat + per-IP auth).

The offline suite disables rate limiting via ``conftest``, so these tests
re-enable a tiny limit (1/min) and clear the limiter state to stay deterministic.
"""
from fastapi.testclient import TestClient

from app import config
from app.backend.app import app
from app.safety import rate_limit


def _clear():
    rate_limit.chat_limiter._hits.clear()
    rate_limit.auth_limiter._hits.clear()


def _patch_engine(monkeypatch):
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


def test_chat_rate_limit_429(monkeypatch, auth_headers):
    monkeypatch.setattr(config, "ANSWERER", "stub")
    monkeypatch.setattr(config, "RATE_LIMIT_CHAT_PER_MIN", 1)
    monkeypatch.setattr(config, "RATE_LIMIT_AUTH_PER_MIN", 0)
    _clear()

    client = TestClient(app)
    first = client.post("/api/chat", json={"message": "hello"}, headers=auth_headers)
    assert first.status_code == 200

    second = client.post("/api/chat", json={"message": "hello again"}, headers=auth_headers)
    assert second.status_code == 429
    assert "rate limit exceeded" in second.json()["detail"]


def test_auth_rate_limit_429(monkeypatch):
    _patch_engine(monkeypatch)
    monkeypatch.setattr(config, "RATE_LIMIT_AUTH_PER_MIN", 1)
    monkeypatch.setattr(config, "RATE_LIMIT_CHAT_PER_MIN", 0)
    _clear()

    client = TestClient(app)
    first = client.post(
        "/api/auth/register",
        json={"email": "a@example.com", "password": "password123"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/register",
        json={"email": "b@example.com", "password": "password123"},
    )
    assert second.status_code == 429
