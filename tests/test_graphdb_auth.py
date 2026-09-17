"""Tests for GraphDB credential plumbing (M4b), offline.

Covers the small ``graphdb_auth.auth()`` helper plus the three call sites that
must forward the ``auth`` kwarg to ``requests``: the SPARQL retrieval layer, the
visual proxy, and ``load.py``.
"""
from types import SimpleNamespace

from app import config


def test_auth_none_when_unset(monkeypatch):
    from app.retrieval import graphdb_auth

    monkeypatch.setattr(config, "GRAPHDB_USER", "")
    assert graphdb_auth.auth() is None


def test_auth_tuple_when_set(monkeypatch):
    from app.retrieval import graphdb_auth

    monkeypatch.setattr(config, "GRAPHDB_USER", "reader")
    monkeypatch.setattr(config, "GRAPHDB_PASSWORD", "s3cret")
    assert graphdb_auth.auth() == ("reader", "s3cret")


def test_run_sparql_sends_auth(monkeypatch):
    from app.retrieval import kg

    captured = {}
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {"results": {"bindings": []}},
    )

    def fake_get(url, **kwargs):
        captured["auth"] = kwargs.get("auth")
        return response

    monkeypatch.setattr(kg.requests, "get", fake_get)
    monkeypatch.setattr(config, "GRAPHDB_USER", "reader")
    monkeypatch.setattr(config, "GRAPHDB_PASSWORD", "s3cret")

    kg.run_sparql("SELECT ?s WHERE { ?s ?p ?o }")

    assert captured["auth"] == ("reader", "s3cret")


def test_proxy_sends_auth(monkeypatch, auth_headers):
    from fastapi.testclient import TestClient

    from app.backend import graphdb_proxy
    from app.backend.app import app

    captured = {}

    class _FakeResp:
        content = b"<html>visualization</html>"
        status_code = 200
        headers = {"content-type": "text/html"}

    def fake_get(url, **kwargs):
        captured["auth"] = kwargs.get("auth")
        return _FakeResp()

    monkeypatch.setattr(graphdb_proxy.requests, "get", fake_get)
    monkeypatch.setattr(config, "GRAPHDB_USER", "reader")
    monkeypatch.setattr(config, "GRAPHDB_PASSWORD", "s3cret")

    client = TestClient(app)
    response = client.get(
        "/api/graphdb/visual",
        params={"uri": "https://example.org/sales-kg/resource/Deal_D007"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert captured["auth"] == ("reader", "s3cret")


def test_load_sends_auth(monkeypatch, tmp_path):
    from app.ingestion import load as load_module

    ontology = tmp_path / "ont.ttl"
    ontology.write_text("@prefix : <urn:> .\n", encoding="utf-8")
    kg_nt = tmp_path / "kg.nt"
    kg_nt.write_text("<urn:s> <urn:p> <urn:o> .\n", encoding="utf-8")

    calls = {"get": [], "post": [], "delete": []}

    class _Resp:
        def __init__(self, status_code=200, json_data=None):
            self.status_code = status_code
            self._json = json_data

        def raise_for_status(self):
            pass

        def json(self):
            return self._json

    def fake_get(url, **kwargs):
        calls["get"].append((url, kwargs))
        if url.endswith("/rest/repositories"):
            return _Resp(json_data=[{"id": "sales-kg"}])
        return _Resp(json_data={"results": {"bindings": [{"n": {"value": "5"}}]}})

    def fake_post(url, **kwargs):
        calls["post"].append((url, kwargs))
        return _Resp(status_code=200)

    def fake_delete(url, **kwargs):
        calls["delete"].append((url, kwargs))
        return _Resp(status_code=200)

    monkeypatch.setattr(load_module.requests, "get", fake_get)
    monkeypatch.setattr(load_module.requests, "post", fake_post)
    monkeypatch.setattr(load_module.requests, "delete", fake_delete)
    monkeypatch.setenv("GRAPHDB_ADMIN_USER", "admin")
    monkeypatch.setenv("GRAPHDB_ADMIN_PASSWORD", "s3cret")

    summary = load_module.load(
        kg_nt=kg_nt, ontology=ontology, extracted_dir=tmp_path / "nonexistent"
    )

    assert summary["total_triples"] == 5
    assert calls["post"], "expected at least one statement POST"
    assert calls["post"][0][1]["auth"] == ("admin", "s3cret")
