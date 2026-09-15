"""Synthetic tests for the trace-shaping helpers (no network, no subprocess).

Covers:
* ``app.agent.opencode`` event/log parsing (namespaced tool names, envelopes),
* ``app.backend.answerers.pydantic_agent`` tool-arg/result shaping,
* ``app.mcp.server`` tool-call log shaping.
"""
import json

from app.agent import opencode
from app.backend.answerers import pydantic_agent
from app.mcp import server as mcp_server


# --- app.agent.opencode -------------------------------------------------------
def test_opencode_normalize_tool_name_namespaced():
    assert opencode._normalize_tool_name("sales-kg_query_kg") == "query_kg"
    assert opencode._normalize_tool_name("sales-kg_keyword_search") == "keyword_search"
    # Unknown tools keep their raw name so dev tools stay visible.
    assert opencode._normalize_tool_name("bash") == "bash"


def test_opencode_parse_events_namespaced_tool_keeps_dict_hits():
    tool_event = {
        "type": "tool_use",
        "part": {
            "type": "tool",
            "tool": "sales-kg_keyword_search",
            "state": {"input": json.dumps({"query": "SSO", "top_k": 1})},
        },
    }
    result_event = {
        "type": "tool",
        "part": {
            "type": "tool",
            "tool": "sales-kg_keyword_search",
            "state": {
                "output": [
                    {"id": "T001", "score": 1.2, "metadata": {"deal_id": "D001"}, "snippet": "s"}
                ]
            },
        },
    }
    text = "\n".join([json.dumps(tool_event), json.dumps(result_event)])

    answer, sources = opencode._parse_events(text)

    assert answer == ""
    assert len(sources) == 1
    assert sources[0]["name"] == "keyword_search"
    assert isinstance(sources[0]["hits"][0], dict)
    assert sources[0]["hits"][0]["id"] == "T001"
    assert sources[0]["total"] == 1


def test_opencode_diff_calls_multiblock_envelope(tmp_path):
    envelope = {
        "content": [
            {"type": "text", "text": json.dumps([{"id": "T001", "score": 1.0}])},
            {"type": "text", "text": json.dumps([{"id": "T002", "score": 0.5}])},
        ]
    }
    line = {"tool": "sales-kg_keyword_search", "output": json.dumps(envelope)}
    path = tmp_path / "mcp_calls.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    records = opencode._diff_calls(path, 0)

    assert len(records) == 1
    assert records[0]["name"] == "keyword_search"
    assert records[0]["total"] == 2
    assert [hit["id"] for hit in records[0]["hits"]] == ["T001", "T002"]
    assert all(isinstance(hit, dict) for hit in records[0]["hits"])


# --- app.backend.answerers.pydantic_agent ------------------------------------
def test_pydantic_kept_input_decodes_json_string_args():
    args = json.dumps({"sparql": "SELECT * WHERE { ?s ?p ?o }", "top_k": 5, "junk": "x"})

    kept = pydantic_agent._kept_input(args)

    assert kept["sparql"] == "SELECT * WHERE { ?s ?p ?o }"
    assert kept["top_k"] == "5"
    assert "junk" not in kept


def test_pydantic_error_result_is_ok_false():
    from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

    call = ToolCallPart(
        tool_name="query_kg",
        args=json.dumps({"sparql": "DELETE WHERE { ?s ?p ?o }"}),
        tool_call_id="c1",
    )
    result = ToolReturnPart(
        tool_name="query_kg",
        content={"error": "refusing DELETE query"},
        tool_call_id="c1",
    )
    messages = [ModelResponse(parts=[call]), ModelRequest(parts=[result])]

    sources = pydantic_agent._sources_from_messages(messages)

    assert len(sources) == 1
    assert sources[0]["ok"] is False
    assert sources[0]["error"] == "refusing DELETE query"


# --- app.mcp.server -----------------------------------------------------------
def test_mcp_log_hits_total_from_bindings():
    outcome = {
        "results": {
            "bindings": [
                {"s": {"type": "uri", "value": "https://example.org/a"}},
                {"s": {"type": "uri", "value": "https://example.org/b"}},
            ]
        }
    }

    hits, total = mcp_server._log_hits_total(outcome)

    assert total == 2
    assert hits[0]["s"]["value"] == "https://example.org/a"
    assert hits[1]["s"]["value"] == "https://example.org/b"
