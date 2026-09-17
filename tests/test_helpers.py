"""Tests for the shared trace-shaping helpers (app.backend.trace_helpers)."""
from app.backend.trace_helpers import extract_iris, normalize_hit, sparql_bindings, truncate


def test_extract_iris_dedupes():
    text = "see https://example.org/a and https://example.org/a again https://example.org/b"
    assert extract_iris(text) == ["https://example.org/a", "https://example.org/b"]


def test_extract_iris_multiple_texts_and_limit():
    assert extract_iris("https://example.org/a", "https://example.org/b", limit=1) == ["https://example.org/a"]


def test_normalize_hit_shapes_dict():
    hit = normalize_hit({"id": "T001", "long": "x" * 600, "n": 3})
    assert hit["id"] == "T001"
    assert len(hit["long"]) == 500
    assert hit["n"] == 3
    assert normalize_hit(42, limit=1) == "4"


def test_truncate():
    assert truncate("hello", limit=3) == "hel"
    assert truncate({"a": 1}, limit=10) == '{"a": 1}'


def test_sparql_bindings():
    assert sparql_bindings({"results": {"bindings": [{"s": {"value": "x"}}]}}) == [{"s": {"value": "x"}}]
    assert sparql_bindings('{"results": {"bindings": [{"s": {"value": "x"}}]}}') == [{"s": {"value": "x"}}]
    assert sparql_bindings("not json") is None
    assert sparql_bindings({"nope": 1}) is None
