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


def test_chat_uses_stub_answerer(monkeypatch):
    monkeypatch.setattr(config, "ANSWERER", "stub")

    response = client.post("/api/chat", json={"message": "ping"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "stub answer to: ping"
    assert body["meta"]["engine"] == "stub"


@pytest.mark.parametrize("message", ["", "   ", "\n"])
def test_chat_empty_message_is_400(message):
    response = client.post("/api/chat", json={"message": message})
    assert response.status_code == 400


def test_transcript_endpoint_known():
    response = client.get("/api/transcripts/T007")
    assert response.status_code == 200
    assert response.json()["deal_id"] == "D007"


def test_transcript_endpoint_unknown_is_404():
    response = client.get("/api/transcripts/NOPE")
    assert response.status_code == 404
