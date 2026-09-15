"""Offline retrieval tests: BM25 keyword search, CSV transcripts, KG guard.

No GraphDB or embedding service is contacted. The optional semantic_search
smoke test runs only when ``chroma_db/`` exists and is skipped otherwise.
"""
import shutil

import pytest

from app import config
from app.retrieval.keyword import keyword_search
from app.retrieval.transcripts import get_transcript, list_transcript_ids


def test_keyword_search_returns_top_chunk():
    hits = keyword_search("SSO data residency", 1)
    assert hits and hits[0]["id"] == "T001"
    assert hits[0]["metadata"]["deal_id"] == "D001"


def test_get_transcript_t007():
    transcript = get_transcript("T007")
    assert transcript["deal_id"] == "D007"


def test_list_transcript_ids_contains_t001():
    assert "T001" in list_transcript_ids()


def test_get_transcript_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        get_transcript("NOPE")


def test_query_kg_delete_raises_valueerror(monkeypatch):
    from app.mcp import server

    # The guard fires before any retrieval call; suppress the best-effort
    # JSON-lines log write so the test leaves no filesystem side effects.
    monkeypatch.setattr(server, "_log_call", lambda *a, **k: None)

    with pytest.raises(ValueError):
        server.query_kg("DELETE WHERE { ?s ?p ?o }")


@pytest.mark.skipif(not config.CHROMA_DIR.exists(), reason="chroma_db not present")
def test_semantic_search_smoke(tmp_path, monkeypatch):
    # Chroma writes to the persistent store merely by opening it, so copy the
    # repo collection to a temp dir to keep the tracked chroma_db/ untouched.
    chroma_copy = tmp_path / "chroma"
    shutil.copytree(config.CHROMA_DIR, chroma_copy)
    monkeypatch.setattr(config, "CHROMA_DIR", chroma_copy)

    from app.retrieval.vector import semantic_search

    hits = semantic_search("SSO data residency", 1)
    assert hits
    assert "id" in hits[0]
