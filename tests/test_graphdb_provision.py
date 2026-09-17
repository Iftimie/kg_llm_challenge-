"""Tests for GraphDB user auto-provisioning on registration (M4e), offline.

No network: ``requests.post``/``requests.put`` are monkeypatched inside
``app.auth.graphdb_provision``. The register test builds a fresh in-memory
SQLite engine (same ``_fresh_engine`` pattern as ``test_auth.py`` /
``test_proxy.py``) so no Postgres or GraphDB is touched.
"""
from fastapi.testclient import TestClient

from app import config
from app.auth import graphdb_provision


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


class _FakeResp:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return {}


def _patch_requests(monkeypatch, post_status=200):
    """Replace requests.post/put with fakes capturing url/auth/json."""
    calls = {"post": [], "put": []}

    def fake_post(url, **kwargs):
        calls["post"].append({"url": url, **kwargs})
        return _FakeResp(post_status)

    def fake_put(url, **kwargs):
        calls["put"].append({"url": url, **kwargs})
        return _FakeResp(200)

    monkeypatch.setattr(graphdb_provision.requests, "post", fake_post)
    monkeypatch.setattr(graphdb_provision.requests, "put", fake_put)
    return calls


def _patch_admin_creds(monkeypatch):
    monkeypatch.setattr(config, "GRAPHDB_URL", "http://graphdb:7200/")
    monkeypatch.setattr(config, "GRAPHDB_REPO", "sales-kg")
    monkeypatch.setattr(config, "GRAPHDB_ADMIN_USER", "admin")
    monkeypatch.setattr(config, "GRAPHDB_ADMIN_PASSWORD", "admin")


def test_create_flow_provisions_readonly_user(monkeypatch):
    _patch_admin_creds(monkeypatch)
    calls = _patch_requests(monkeypatch, post_status=200)

    graphdb_provision.provision_user("u@x.com", "password123")

    assert len(calls["post"]) == 1
    assert len(calls["put"]) == 1

    post = calls["post"][0]
    assert post["url"].endswith("/rest/security/users/u@x.com")
    assert post["auth"] == ("admin", "admin")
    assert post["json"] == {"username": "u@x.com", "password": "password123"}

    put = calls["put"][0]
    assert put["url"].endswith("/rest/security/users/u@x.com")
    assert put["auth"] == ("admin", "admin")
    assert put["json"]["username"] == "u@x.com"
    assert put["json"]["password"] == "password123"
    assert put["json"]["grantedAuthorities"] == ["READ_REPO_sales-kg"]


def test_existing_user_flow_still_puts_with_password_refresh(monkeypatch):
    _patch_admin_creds(monkeypatch)
    calls = _patch_requests(monkeypatch, post_status=400)

    graphdb_provision.provision_user("u@x.com", "newpass")

    assert len(calls["post"]) == 1
    assert len(calls["put"]) == 1

    put = calls["put"][0]
    assert put["url"].endswith("/rest/security/users/u@x.com")
    assert put["json"]["password"] == "newpass"
    assert put["json"]["grantedAuthorities"] == ["READ_REPO_sales-kg"]


def test_register_succeeds_despite_graphdb_down(monkeypatch):
    from app.backend.app import app

    _fresh_engine(monkeypatch)

    def boom(username, password_plaintext):
        raise ConnectionError("graphdb down")

    monkeypatch.setattr(graphdb_provision, "provision_user", boom)

    client = TestClient(app)
    response = client.post(
        "/api/auth/register",
        json={"email": "u@x.com", "password": "password123"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "u@x.com"
