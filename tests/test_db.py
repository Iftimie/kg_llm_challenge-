"""Database infra tests (M2): in-memory SQLite unit coverage.

No Postgres is required; these use a fresh ``sqlite:///:memory:`` engine with a
single shared connection (StaticPool) so schema and rows persist per engine.
"""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.app import app
from app.db import engine as db_engine
from app.db.models import Base, Chat, Message, User


def _fresh_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_tables_created():
    engine = _fresh_engine()
    names = set(inspect(engine).get_table_names())
    assert {"users", "chats", "messages", "jobs"} <= names


def test_user_chat_message_roundtrip():
    engine = _fresh_engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        user = User(email="a@example.com", password_hash="hash")
        chat = Chat(user=user)
        message = Message(chat=chat, role="user", content="hello")
        db.add(user)
        db.commit()

        loaded_user = db.get(User, user.id)
        assert loaded_user.email == "a@example.com"

        loaded_chat = db.get(Chat, chat.id)
        assert loaded_chat.user_id == loaded_user.id
        assert loaded_chat.user is loaded_user

        loaded_message = db.get(Message, message.id)
        assert loaded_message.chat_id == loaded_chat.id
        assert loaded_message.role == "user"
        assert loaded_message.content == "hello"


def test_health_reports_db(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(db_engine, "get_engine", lambda: engine)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["db"] == "ok"
    assert body["status"] == "ok"
    assert "answerer" in body
