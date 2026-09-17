"""Shared pytest fixtures for the API test suite.

The default suite must stay offline: no LLM, no GraphDB. Tests that need live
services opt in with ``pytestmark = pytest.mark.live`` (see ``pytest.ini``) and
request the ``live_guard`` fixture, which skips when a dependency is missing.
"""
import shutil

import pytest
import requests

from app import config


@pytest.fixture(autouse=True)
def _offline_register(monkeypatch):
    """Keep the default suite offline: skip GraphDB auto-provisioning.

    ``register()`` synchronously provisions a read-only GraphDB user, which
    would otherwise make every ``/api/auth/register`` call in the suite issue a
    real POST+PUT to GraphDB (~10s each). Tests that need the real provisioning
    call ``app.auth.graphdb_provision.provision_user`` directly (with mocked
    ``requests``) or set ``config.GRAPHDB_AUTO_PROVISION`` back to ``"1"``.
    """
    monkeypatch.setattr(config, "GRAPHDB_AUTO_PROVISION", "0")


@pytest.fixture(autouse=True)
def _disable_rate_limit(monkeypatch):
    """Disable in-memory rate limiting so the offline suite never 429s.

    Every test registers/logs in through the ``auth_headers`` fixture from the
    same ``testclient`` IP; the default auth limit would trip almost immediately.
    """
    monkeypatch.setattr(config, "RATE_LIMIT_CHAT_PER_MIN", 0)
    monkeypatch.setattr(config, "RATE_LIMIT_AUTH_PER_MIN", 0)


@pytest.fixture
def session():
    """Fresh in-memory SQLite session (full schema per test, not autouse)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def stub_env(monkeypatch):
    """Force the offline ``stub`` answerer for the duration of a test."""
    monkeypatch.setattr(config, "ANSWERER", "stub")
    return "stub"


def _setup_client(monkeypatch):
    """Patch a fresh in-memory engine and return a ``TestClient`` for the app."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from fastapi.testclient import TestClient

    from app.backend.app import app
    from app.db import engine as db_engine
    from app.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_engine, "get_engine", lambda: engine)
    return TestClient(app)


def _register_login(client, email: str) -> dict:
    register = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert register.status_code == 201, register.text
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def auth_headers(monkeypatch):
    """Register+login a regular (non-admin) user; return auth headers."""
    client = _setup_client(monkeypatch)
    return _register_login(client, "test@example.com")


@pytest.fixture
def admin_headers(monkeypatch):
    """Register+login an admin user (email in ``ADMIN_EMAILS``); return headers."""
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"admin@example.com"})
    client = _setup_client(monkeypatch)
    return _register_login(client, "admin@example.com")


def needs_live():
    """Skip the calling test unless every live dependency looks available."""
    if shutil.which("opencode") is None:
        pytest.skip("opencode binary not on PATH")
    if not config.OPENROUTER_API_KEY:
        pytest.skip("OPENROUTER_API_KEY not set")
    try:
        requests.get(config.GRAPHDB_URL, timeout=2)
    except Exception as exc:  # any failure means "GraphDB not up"
        pytest.skip(f"GraphDB not reachable at {config.GRAPHDB_URL}: {exc}")


@pytest.fixture
def live_guard():
    """Skip live tests when opencode, the key or GraphDB are unavailable."""
    needs_live()
