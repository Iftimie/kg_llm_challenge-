"""M3 MCP server exposing read-only retrieval tools over the sales knowledge graph.

Run with ``python -m app.mcp.server``. The FastMCP dependency is imported here only,
so importing individual helpers (e.g. :mod:`app.mcp.guards`) stays dependency-free.
"""
from mcp.server.fastmcp import FastMCP

from app import config
from app.mcp.guards import MAX_ROWS, MAX_TOP_K, SPARQL_TIMEOUT, assert_readonly, clamp_top_k
from app.retrieval import keyword, kg, transcripts, vector

_SCHEMA_CHAR_LIMIT = 20000

mcp = FastMCP("sales-kg")


@mcp.tool()
def query_kg(sparql: str) -> dict:
    """Run a read-only SPARQL query against the GraphDB repository."""
    assert_readonly(sparql)
    try:
        return kg.run_sparql(sparql, timeout=SPARQL_TIMEOUT, max_rows=MAX_ROWS)
    except RuntimeError as exc:
        return {"error": str(exc)}


@mcp.tool()
def semantic_search(query: str, top_k: int = 3) -> list:
    """Return transcript chunks semantically similar to ``query``."""
    return vector.semantic_search(query, clamp_top_k(top_k, hi=MAX_TOP_K))


@mcp.tool()
def keyword_search(query: str, top_k: int = 3) -> list:
    """Return transcript chunks ranked by BM25 keyword relevance to ``query``."""
    return keyword.keyword_search(query, clamp_top_k(top_k, hi=MAX_TOP_K))


@mcp.tool()
def get_transcript(transcript_id: str) -> dict:
    """Return one transcript by id."""
    try:
        return transcripts.get_transcript(transcript_id)
    except KeyError as exc:
        return {"error": str(exc)}


@mcp.tool()
def describe_kg_schema() -> dict:
    """Return the canonical ontology text used to describe the knowledge graph."""
    path = config.ONTOLOGY_PATH
    text = path.read_text(encoding="utf-8")
    truncated = len(text) > _SCHEMA_CHAR_LIMIT
    return {
        "ontology_path": str(path),
        "size": len(text),
        "text": text[:_SCHEMA_CHAR_LIMIT],
        "truncated": truncated,
    }


if __name__ == "__main__":
    mcp.run()
