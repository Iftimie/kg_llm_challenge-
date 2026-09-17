"""End-to-end API contract tests over the in-process FastAPI app (offline).

Locks the public ``/api/chat``, ``/api/transcripts/*`` and ``/health`` contracts
for later milestones. Requests go through Starlette's TestClient, so no server
or network is involved; the ``stub_env`` fixture pins ``ANSWERER=stub``.
"""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.backend.app import app

client = TestClient(app)


def test_chat_stub_contract_shape(stub_env, auth_headers):
    response = client.post("/api/chat", json={"message": "ping"}, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "sources", "meta"}
    assert isinstance(body["answer"], str)
    assert isinstance(body["sources"], list)
    assert isinstance(body["meta"], dict)


def test_chat_stub_meta_evidence_fields(stub_env, auth_headers):
    response = client.post("/api/chat", json={"message": "ping"}, headers=auth_headers)

    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["engine"] == "stub"
    assert meta["graphdb_url"] == config.GRAPHDB_URL
    assert meta["graphdb_repo"] == config.GRAPHDB_REPO
    assert meta["iris"] == []


def test_chat_history_accepted(stub_env, auth_headers):
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]

    response = client.post(
        "/api/chat", json={"message": "ping", "history": history}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "stub answer to: ping"


@pytest.mark.parametrize("message", ["", "   "])
def test_chat_empty_message_400(message, auth_headers):
    response = client.post("/api/chat", json={"message": message}, headers=auth_headers)
    assert response.status_code == 400


def test_chat_runtime_error_maps_502(monkeypatch, auth_headers):
    def _boom():
        raise RuntimeError("boom")

    # app.py imports get_answerer by name, so patch the app module's binding.
    monkeypatch.setattr("app.backend.app.get_answerer", _boom)

    response = client.post("/api/chat", json={"message": "ping"}, headers=auth_headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "boom"


def test_transcript_contract_fields(auth_headers):
    response = client.get("/api/transcripts/T007", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert "transcript_id" in body
    assert "deal_id" in body
    assert body["transcript_id"] == "T007"
    assert body["deal_id"] == "D007"


def test_transcript_unknown_404(auth_headers):
    response = client.get("/api/transcripts/NOPE", headers=auth_headers)
    assert response.status_code == 404


def test_health_reports_answerer():
    response = client.get("/health")

    assert response.status_code == 200
    assert "answerer" in response.json()
