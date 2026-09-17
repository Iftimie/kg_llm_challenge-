"""Tests for the authenticated GraphDB visual proxy (M4a), offline.

Follows the in-memory SQLite pattern from ``test_auth.py``: each test builds a
fresh engine and patches ``app.db.engine.get_engine`` for its duration. The
upstream ``requests.get`` call is always mocked so no GraphDB is contacted.
"""
import pytest
import requests
from fastapi.testclient import TestClient

from app import config
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
    return login.json()["access_token"]


class _FakeResp:
    def __init__(self, content=b"<html>visualization</html>", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html"}


URI = "https://example.org/sales-kg/resource/Deal_D007"


def test_proxy_requires_auth(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/graphdb/visual", params={"uri": URI})

    assert response.status_code == 401


def test_proxy_cookie_auth_ok(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)
    token = _register_and_login(client)
    monkeypatch.setattr(
        "app.backend.graphdb_proxy.requests.get", lambda *a, **kw: _FakeResp()
    )

    response = client.get(
        "/api/graphdb/visual",
        params={"uri": URI, "role": "subject"},
        cookies={"sales_token": token},
    )

    assert response.status_code == 200
    assert response.text == "<html>visualization</html>"


def test_proxy_bearer_auth_ok(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)
    token = _register_and_login(client)
    monkeypatch.setattr(
        "app.backend.graphdb_proxy.requests.get", lambda *a, **kw: _FakeResp()
    )

    response = client.get(
        "/api/graphdb/visual",
        params={"uri": URI},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.text == "<html>visualization</html>"


def test_proxy_rejects_invalid_role_400(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)
    token = _register_and_login(client)

    response = client.get(
        "/api/graphdb/visual",
        params={"uri": URI, "role": "bogus"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


@pytest.mark.parametrize("uri", ["not a uri", "ftp://x/y", "http://a b/c"])
def test_proxy_rejects_bad_uri_400(monkeypatch, uri):
    _fresh_engine(monkeypatch)
    client = TestClient(app)
    token = _register_and_login(client)

    response = client.get(
        "/api/graphdb/visual",
        params={"uri": uri},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


def test_proxy_sends_accept_html(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)
    token = _register_and_login(client)

    calls = {}

    def fake_get(url, params=None, timeout=None, **kwargs):
        calls["headers"] = kwargs.get("headers")
        return _FakeResp()

    monkeypatch.setattr("app.backend.graphdb_proxy.requests.get", fake_get)

    response = client.get(
        "/api/graphdb/visual",
        params={"uri": URI, "role": "subject"},
        cookies={"sales_token": token},
    )

    assert response.status_code == 200
    assert calls["headers"]["Accept"] == "text/html"


def test_proxy_upstream_fixed_host(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)
    token = _register_and_login(client)

    calls = {}

    def fake_get(url, params=None, timeout=None, **kwargs):
        calls["url"] = url
        calls["params"] = params
        return _FakeResp()

    monkeypatch.setattr("app.backend.graphdb_proxy.requests.get", fake_get)

    user_uri = "https://attacker.example/evil"
    response = client.get(
        "/api/graphdb/visual",
        params={"uri": user_uri, "role": "subject"},
        cookies={"sales_token": token},
    )

    assert response.status_code == 200
    assert calls["url"].startswith(config.GRAPHDB_URL)
    assert calls["params"]["uri"] == user_uri
    assert calls["params"]["role"] == "subject"


def test_proxy_upstream_error_502(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(app)
    token = _register_and_login(client)

    def fake_get(*args, **kwargs):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("app.backend.graphdb_proxy.requests.get", fake_get)

    response = client.get(
        "/api/graphdb/visual",
        params={"uri": URI},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502


def test_compose_graphdb_publishes_7200():
    import yaml
    from pathlib import Path

    compose_path = Path(__file__).resolve().parent.parent / "docker-compose.yml"
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    graphdb = data["services"]["graphdb"]
    assert "7200" in str(graphdb.get("ports", []))


def test_compose_graphdb_demo_creds():
    import yaml
    from pathlib import Path

    compose_path = Path(__file__).resolve().parent.parent / "docker-compose.yml"
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    app_env = data["services"]["app"]["environment"]
    assert "GRAPHDB_USER" in str(app_env)
    assert "reader" in str(app_env)
