"""Live structural tests for the OpenCode agent answerer (``ANSWERER=agent``).

Default-off: ``pytest.ini`` sets ``addopts = -m "not live"``. Run explicitly
with ``python -m pytest -m live``. The ``live_guard`` fixture skips when
``opencode``, ``OPENROUTER_API_KEY`` or GraphDB are unavailable. These tests
check structure only -- never answer exactness.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app import config
from app.backend.app import app

pytestmark = pytest.mark.live

client = TestClient(app)

_TOOL_NAMES = {
    "query_kg",
    "keyword_search",
    "semantic_search",
    "get_transcript",
    "describe_kg_schema",
}
# Markdown link, e.g. ``[Deal D007](https://.../resource?uri=...)``.
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\(https?://[^)]+\)")


def _ask_agent(monkeypatch, message):
    """POST ``message`` through the agent answerer and return the JSON body."""
    monkeypatch.setattr(config, "ANSWERER", "agent")
    response = client.post("/api/chat", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def _q_easy():
    return (config.QA_DIR / "q_easy.txt").read_text(encoding="utf-8").strip()


def test_agent_chat_structure_d007(live_guard, monkeypatch):
    body = _ask_agent(monkeypatch, _q_easy())

    assert set(body) == {"answer", "sources", "meta"}

    assert isinstance(body["answer"], str)
    assert len(body["answer"]) > 20

    meta = body["meta"]
    assert meta["engine"] == "agent"
    for key in ("model", "graphdb_url", "graphdb_repo"):
        assert key in meta, f"meta missing {key!r}"

    assert meta["steps"] == len(body["sources"])


def test_agent_sources_trace_shape(live_guard, monkeypatch):
    body = _ask_agent(monkeypatch, _q_easy())

    sources = body["sources"]
    assert sources, "agent should cite at least one retrieval source"
    assert all("tool" in source and "name" in source for source in sources)
    assert any(source["name"] in _TOOL_NAMES for source in sources)

    has_markdown_link = bool(_MD_LINK_RE.search(body["answer"]))
    has_iris = bool(body["meta"].get("iris"))
    assert has_markdown_link or has_iris, "answer/meta should expose a GraphDB IRI"
