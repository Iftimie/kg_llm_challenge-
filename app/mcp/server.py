"""M3 MCP server exposing read-only retrieval tools over the sales knowledge graph.

Run with ``python -m app.mcp.server``. The FastMCP dependency is imported here only,
so importing individual helpers (e.g. :mod:`app.mcp.guards`) stays dependency-free.
"""
import json
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from app import config
from app.mcp.guards import MAX_ROWS, MAX_TOP_K, SPARQL_TIMEOUT, assert_readonly, clamp_top_k
from app.retrieval import keyword, kg, transcripts, vector

_SCHEMA_CHAR_LIMIT = 20000

# --- Call logging -------------------------------------------------------------
# Each tool appends one JSON line describing the call to config.MCP_LOG so the
# agent harness can rebuild the retrieval trace from server-side ground truth
# instead of guessing it from stdout events.
_LOG_INPUT_KEYS = ("sparql", "query", "top_k", "transcript_id")
_LOG_INPUT_CHARS = 2000
_LOG_HITS = 5
_LOG_HIT_CHARS = 200


def _kept_input(inp) -> dict:
    """Keep only the trace-relevant input keys, each capped at 2000 chars."""
    kept = {}
    if not isinstance(inp, dict):
        return kept
    for key in _LOG_INPUT_KEYS:
        value = inp.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
        kept[key] = value[:_LOG_INPUT_CHARS]
    return kept


def _log_string(value) -> str:
    """Render ``value`` as a string capped at the hit character limit."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    return text[:_LOG_HIT_CHARS]


def _log_hit(item):
    """Keep dict hits as dicts (string values truncated); stringify the rest."""
    if isinstance(item, dict):
        return {
            key: (
                value[:_LOG_HIT_CHARS]
                if isinstance(value, str) and len(value) > _LOG_HIT_CHARS
                else value
            )
            for key, value in item.items()
        }
    return _log_string(item)


def _log_hits_total(outcome):
    """Return ``(hits, total)`` for a successful tool result."""
    if isinstance(outcome, dict):
        results = outcome.get("results")
        bindings = results.get("bindings") if isinstance(results, dict) else None
        if isinstance(bindings, list):
            return [_log_hit(row) for row in bindings[:_LOG_HITS]], len(bindings)
        return [_log_hit(outcome)], 1
    if isinstance(outcome, list):
        return [_log_hit(item) for item in outcome[:_LOG_HITS]], len(outcome)
    text = _log_string(outcome)
    return ([text] if text else []), (1 if text else 0)


def _log_call(tool, inp, outcome) -> None:
    """Append one JSON line describing a tool call to ``config.MCP_LOG``.

    ``outcome`` is either the successful return value or a dict containing an
    ``error`` key. Logging is best-effort: any failure here must never break a
    tool, so every exception is swallowed.
    """
    try:
        error = outcome.get("error") if isinstance(outcome, dict) else None
        if error:
            hits, total = [], 0
        else:
            hits, total = _log_hits_total(outcome)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "input": _kept_input(inp),
            "ok": not error,
            "total": total,
            "hits": hits,
        }
        if error:
            record["error"] = str(error)
        config.MCP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(config.MCP_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


mcp = FastMCP("sales-kg")


@mcp.tool()
def query_kg(sparql: str) -> dict:
    """Run a read-only SPARQL query against the GraphDB repository."""
    inp = {"sparql": sparql}
    try:
        assert_readonly(sparql)
    except ValueError as exc:
        _log_call("query_kg", inp, {"error": str(exc)})
        raise
    try:
        result = kg.run_sparql(sparql, timeout=SPARQL_TIMEOUT, max_rows=MAX_ROWS)
    except RuntimeError as exc:
        _log_call("query_kg", inp, {"error": str(exc)})
        return {"error": str(exc)}
    _log_call("query_kg", inp, result)
    return result


@mcp.tool()
def semantic_search(query: str, top_k: int = 3) -> list:
    """Return transcript chunks semantically similar to ``query``."""
    inp = {"query": query, "top_k": top_k}
    try:
        result = vector.semantic_search(query, clamp_top_k(top_k, hi=MAX_TOP_K))
    except Exception as exc:
        _log_call("semantic_search", inp, {"error": str(exc)})
        raise
    _log_call("semantic_search", inp, result)
    return result


@mcp.tool()
def keyword_search(query: str, top_k: int = 3) -> list:
    """Return transcript chunks ranked by BM25 keyword relevance to ``query``."""
    inp = {"query": query, "top_k": top_k}
    try:
        result = keyword.keyword_search(query, clamp_top_k(top_k, hi=MAX_TOP_K))
    except Exception as exc:
        _log_call("keyword_search", inp, {"error": str(exc)})
        raise
    _log_call("keyword_search", inp, result)
    return result


@mcp.tool()
def get_transcript(transcript_id: str) -> dict:
    """Return one transcript by id."""
    inp = {"transcript_id": transcript_id}
    try:
        result = transcripts.get_transcript(transcript_id)
    except KeyError as exc:
        _log_call("get_transcript", inp, {"error": str(exc)})
        return {"error": str(exc)}
    except Exception as exc:
        _log_call("get_transcript", inp, {"error": str(exc)})
        raise
    _log_call("get_transcript", inp, result)
    return result


@mcp.tool()
def describe_kg_schema() -> dict:
    """Return the canonical ontology text used to describe the knowledge graph."""
    inp = {}
    try:
        path = config.ONTOLOGY_PATH
        text = path.read_text(encoding="utf-8")
        truncated = len(text) > _SCHEMA_CHAR_LIMIT
        result = {
            "ontology_path": str(path),
            "size": len(text),
            "text": text[:_SCHEMA_CHAR_LIMIT],
            "truncated": truncated,
        }
    except Exception as exc:
        _log_call("describe_kg_schema", inp, {"error": str(exc)})
        raise
    _log_call("describe_kg_schema", inp, result)
    return result


if __name__ == "__main__":
    mcp.run()
