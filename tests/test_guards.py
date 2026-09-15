"""Read-only guard tests: query-form validation and top-k clamping.

Offline and stdlib-only; imports :mod:`app.mcp.guards` directly so no MCP
server or network dependency is involved.
"""
import pytest

from app.mcp.guards import assert_readonly, clamp_top_k


def test_assert_readonly_accepts_plain_select():
    assert assert_readonly("SELECT ?s WHERE { ?s ?p ?o }") == "SELECT"


def test_assert_readonly_accepts_multiline_prefix_select():
    query = (
        "PREFIX crm: <https://example.org/crm/>\n"
        "SELECT ?s ?o\n"
        "WHERE { ?s crm:name ?o }\n"
        "LIMIT 5"
    )
    assert assert_readonly(query) == "SELECT"


def test_assert_readonly_accepts_single_line_rdf_schema_iri():
    # Regression: the '#' inside the rdf-schema IRI used to be treated as a
    # line comment, stripping the trailing SELECT and causing a false refusal.
    query = (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
        "SELECT ?s WHERE { ?s rdfs:label ?o }"
    )
    assert assert_readonly(query) == "SELECT"


@pytest.mark.parametrize("query", ["ASK { ?s ?p ?o }", "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "DESCRIBE ?s"])
def test_assert_readonly_accepts_other_read_forms(query):
    assert assert_readonly(query) in ("ASK", "CONSTRUCT", "DESCRIBE")


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <urn:x> <urn:p> <urn:o> }",
        "DELETE WHERE { ?s ?p ?o }",
        "DROP GRAPH <urn:g>",
        "CLEAR GRAPH <urn:g>",
        "LOAD <urn:g>",
        "CREATE GRAPH <urn:g>",
    ],
)
def test_assert_readonly_rejects_mutations(query):
    with pytest.raises(ValueError):
        assert_readonly(query)


def test_assert_readonly_rejects_empty():
    with pytest.raises(ValueError):
        assert_readonly("")
    with pytest.raises(ValueError):
        assert_readonly("   \n  ")


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 1),
        (-5, 1),
        (99, 10),
        (11, 10),
        ("bad", 3),
        (None, 3),
    ],
)
def test_clamp_top_k_edges(value, expected):
    assert clamp_top_k(value) == expected
