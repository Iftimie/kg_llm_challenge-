"""Offline retrieval tests: BM25 keyword search, CSV transcripts, KG guard.

No GraphDB or embedding service is contacted. The optional semantic_search
smoke test runs only when ``chroma_db/`` exists and is skipped otherwise.
"""
import shutil
from types import SimpleNamespace

import pytest

from app import config
from app.retrieval.keyword import keyword_search
from app.retrieval.transcripts import get_transcript, list_transcript_ids


class _RequestsGetSpy:
    """Callable spy for ``requests.get`` that records calls.

    With no ``response`` it raises ``AssertionError`` when invoked, so a guard
    failure surfaces loudly if the write query ever reaches the network.
    """

    def __init__(self, response=None):
        self.response = response
        self.called = False
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.called = True
        self.calls.append((args, kwargs))
        if self.response is None:
            raise AssertionError("requests.get must not be called")
        return self.response


def _patch_kg_get(monkeypatch, response=None):
    """Patch ``app.retrieval.kg.requests.get`` with a spy and return it."""
    from app.retrieval import kg

    spy = _RequestsGetSpy(response)
    monkeypatch.setattr(kg.requests, "get", spy)
    return spy


def test_keyword_search_returns_top_chunk():
    hits = keyword_search("SSO data residency", 1)
    assert hits and hits[0]["id"] == "T001"
    assert hits[0]["metadata"]["deal_id"] == "D001"


def test_get_transcript_t007():
    transcript = get_transcript("T007")
    assert transcript["deal_id"] == "D007"
    assert transcript["contact_ids"] == ["C013", "C014"]


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


def test_run_sparql_rejects_insert(monkeypatch):
    from app.retrieval import kg

    spy = _patch_kg_get(monkeypatch)
    with pytest.raises(ValueError):
        kg.run_sparql("INSERT DATA { <urn:x> <urn:p> <urn:o> }")
    assert spy.called is False


def test_run_sparql_rejects_delete(monkeypatch):
    from app.retrieval import kg

    spy = _patch_kg_get(monkeypatch)
    with pytest.raises(ValueError):
        kg.run_sparql("DELETE WHERE { ?s ?p ?o }")
    assert spy.called is False


def test_run_sparql_rejects_stacked(monkeypatch):
    from app.retrieval import kg

    spy = _patch_kg_get(monkeypatch)
    with pytest.raises(ValueError):
        kg.run_sparql("SELECT ?s WHERE { ?s ?p ?o } ; DELETE WHERE { ?s ?p ?o }")
    assert spy.called is False


def test_run_sparql_rejects_comment_hidden(monkeypatch):
    from app.retrieval import kg

    spy = _patch_kg_get(monkeypatch)
    query = (
        "SELECT ?s WHERE { ?s ?p ?o } # comment\n"
        "INSERT DATA { <urn:x> <urn:p> <urn:o> }"
    )
    with pytest.raises(ValueError):
        kg.run_sparql(query)
    assert spy.called is False


def test_run_sparql_select_still_returns(monkeypatch):
    from app.retrieval import kg

    query = "SELECT ?s WHERE { ?s ?p ?o }"
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {"results": {"bindings": [{"s": {"value": "x"}}]}},
    )
    spy = _patch_kg_get(monkeypatch, response)

    payload = kg.run_sparql(query)

    assert payload["results"]["bindings"] == [{"s": {"value": "x"}}]
    assert spy.called is True
    assert spy.calls[0][1]["params"]["query"] == query


def test_factory_baseline_removed(monkeypatch):
    from app.backend import factory
    from app.backend.answerers import agent as agent_module

    monkeypatch.setattr(config, "ANSWERER", "baseline")
    with pytest.raises(ValueError):
        factory.get_answerer()

    # Default (empty/None) ANSWERER resolves to the agent module.
    monkeypatch.setattr(config, "ANSWERER", "")
    assert factory.get_answerer() is agent_module
    monkeypatch.setattr(config, "ANSWERER", None)
    assert factory.get_answerer() is agent_module


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
