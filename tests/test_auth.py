"""Auth + chat-persistence API tests (M3a), offline, in-memory SQLite.

Each test builds a fresh in-memory engine via ``_fresh_engine`` and patches
``app.db.engine.get_engine`` (read at request time by ``get_db``) for the test's
duration. No Postgres, LLM or GraphDB is touched.
"""
from fastapi.testclient import TestClient

from app.backend.app import app


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


def _register_and_login(client, email="test@example.com", password="password123"):
    register = client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_register_login_happy(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)

    register = client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert register.status_code == 201
    assert register.json()["email"] == "test@example.com"
    assert register.json()["id"] > 0

    login = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "test@example.com"


def test_register_duplicate_409(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)

    first = client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert second.status_code == 409


def test_wrong_password_401(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)

    register = client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert register.status_code == 201

    login = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "wrong-password"},
    )
    assert login.status_code == 401
    assert login.json()["detail"] == "invalid credentials"


def test_chat_unauth_401(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "ping"})
    assert response.status_code == 401


def test_me_unauth_401(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_user_a_cannot_read_user_b_chat(monkeypatch, stub_env):
    _fresh_engine(monkeypatch)
    client = TestClient(app)

    a_headers = _register_and_login(client, "a@example.com")
    chat = client.post("/api/chat", json={"message": "ping"}, headers=a_headers)
    assert chat.status_code == 200

    b_headers = _register_and_login(client, "b@example.com")
    b_chats = client.get("/api/chats", headers=b_headers)
    assert b_chats.status_code == 200
    assert b_chats.json()["chats"] == []

    # User A sees exactly its own exchange; user B's token cannot reach it.
    a_chats = client.get("/api/chats", headers=a_headers)
    assert a_chats.status_code == 200
    chats = a_chats.json()["chats"]
    assert len(chats) == 1
    assert [m["role"] for m in chats[0]["messages"]] == ["user", "assistant"]
    assert chats[0]["messages"][0]["content"] == "ping"
