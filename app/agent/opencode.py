"""M4 agent harness: invoke OpenCode headlessly via :mod:`subprocess`.

The module is stdlib-only. It builds a single prompt from the system
instructions, the conversation history, and the current question, then runs
``opencode run --format json`` in the repository root. OpenCode emits one JSON
object per line (JSON-lines); this module best-effort parses those events to
recover the final answer text, the tool calls it made, and any IRIs mentioned
in the answer.

No network calls are made here. OpenCode may contact the configured model
provider when the host actually runs it.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app import config

from app.backend.trace_helpers import (
    extract_iris as _extract_iris,
    normalize_hit as _normalize_hit,
    sparql_bindings as _sparql_bindings,
    truncate as _truncate,
)

_ENGINE = "agent"
_SYSTEM_PROMPT = Path(__file__).with_name("system.md")

# Tool names we recognize in the OpenCode event stream.
_TOOL_NAMES = (
    "query_kg",
    "semantic_search",
    "keyword_search",
    "get_transcript",
    "describe_kg_schema",
)
_TOOL_INPUT_KEYS = ("input", "args", "arguments", "parameters")
_INPUT_KEEP = ("sparql", "query", "top_k", "transcript_id")
_ANSWER_KEYS = ("text", "content", "message", "answer", "output", "result")
_RESULT_KEYS = ("output", "result", "response", "data", "observation")
_TEXT_BLOCK_TYPES = ("text",)

# Trace-shaping caps: hits lists and the longest string kept per hit.
_KG_HITS = 5
_SEARCH_HITS = 5
_COLOCATED_LINES = 3


def _resolve_model() -> str:
    """Return an OpenCode ``provider/model`` id, defaulting to DeepSeek Flash."""
    return (config.OPENCODE_MODEL or "deepseek/deepseek-flash").strip()


def _format_history(history) -> str:
    """Render prior turns as plain ``Role: content`` lines."""
    if not history:
        return ""
    lines = []
    for turn in history:
        if isinstance(turn, dict):
            role = str(turn.get("role", "user")).strip() or "user"
            content = str(turn.get("content", "")).strip()
            if content:
                lines.append(f"{role.capitalize()}: {content}")
        elif turn is not None:
            text = str(turn).strip()
            if text:
                lines.append(f"User: {text}")
    return "\n".join(lines)


def _build_prompt(question: str, history) -> str:
    system = _SYSTEM_PROMPT.read_text(encoding="utf-8").strip()
    # Append the competency SPARQL examples (config.COMPETENCY_QUERIES); a
    # missing or empty file degrades gracefully to the bare system prompt.
    try:
        examples = config.COMPETENCY_QUERIES.read_text(encoding="utf-8").strip()
    except OSError:
        examples = ""
    if examples:
        system = (
            f"{system}\n\n## SPARQL examples (follow these patterns)\n\n{examples}"
        )
    history_text = _format_history(history)
    return "\n".join(
        [
            system,
            "",
            "## Conversation so far",
            history_text if history_text else "(none)",
            "",
            "## Current question",
            str(question),
        ]
    )


def _walk(node, visit, budget) -> None:
    """Depth-first walk, calling ``visit`` on dict nodes, capped by ``budget``."""
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(node, dict):
        visit(node)
        for value in node.values():
            if budget[0] <= 0:
                break
            _walk(value, visit, budget)
    elif isinstance(node, list):
        for item in node:
            if budget[0] <= 0:
                break
            _walk(item, visit, budget)


def _text_from_value(value):
    """Return answer text from a string or a list of content blocks."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, list):
        parts = []
        for block in value:
            if not isinstance(block, dict):
                continue
            if block.get("type") in _TEXT_BLOCK_TYPES:
                part = block.get("text")
                if isinstance(part, str) and part.strip():
                    parts.append(part.strip())
        if parts:
            return "\n".join(parts)
    return None


def _consider_answer(node, best) -> None:
    """Record the highest-priority non-empty answer field on ``node``."""
    for index, key in enumerate(_ANSWER_KEYS):
        if key not in node:
            continue
        candidate = _text_from_value(node.get(key))
        if not candidate:
            continue
        if best[0] is None or index <= best[0]:
            best[0] = index
            best[1] = candidate
        break


def _result_value(node):
    """Return the first non-empty result payload value on ``node``, else ``None``.

    Real ``tool_use`` events nest the payload under ``part.state.output``, so the
    node itself is checked first and its ``state`` dict is used as a fallback.
    """
    if not isinstance(node, dict):
        return None
    containers = (node, node.get("state"))
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in _RESULT_KEYS:
            if key in container:
                value = container[key]
                if value in (None, "", [], {}):
                    continue
                return value
    return None


def _is_retrieval_tool(tool):
    """Return ``True`` for a known retrieval tool, namespaced or plain.

    OpenCode exposes MCP tools either as plain names (``query_kg``) or
    namespaced after the server (``sales-kg_query_kg``); both should count as
    known so result payloads attach and the trace marks them.
    """
    if not isinstance(tool, str) or not tool:
        return False
    if tool in _TOOL_NAMES:
        return True
    return any(tool.endswith(f"_{name}") for name in _TOOL_NAMES)


def _normalize_tool_name(tool):
    """Strip a leading ``<server>_``/``<server>-`` prefix from a known tool.

    ``sales-kg_query_kg`` -> ``query_kg``; unknown tools keep their raw name so
    dev tools stay visible. The raw string is preserved separately in ``tool``.
    """
    if not isinstance(tool, str) or not tool:
        return tool
    if tool in _TOOL_NAMES:
        return tool
    for name in _TOOL_NAMES:
        if tool.endswith(f"_{name}") or tool.endswith(f"-{name}"):
            return name
    return tool


def _tool_from_node(node, event_type):
    """Return a generic tool-call record for a ``tool_use`` node, else ``None``.

    Every ``tool_use`` event is recorded -- including non-retrieval dev tools
    such as ``bash``, ``read``, ``grep``, and ``task`` (``known: False``) -- so
    that file-snooping by the runtime stays visible in the trace. Input is read
    from the node or, as a fallback, from ``node["state"]["input"]``.
    """
    if event_type != "tool_use" or not isinstance(node, dict):
        return None
    tool = node.get("tool")
    if not isinstance(tool, str) or not tool:
        return None
    # Only the direct ``part`` node (``type: "tool"``) is a real call. The
    # ``task`` tool nests its subagent's calls under ``state.metadata.summary``
    # with the same ``tool``/``state`` shape; those must not be double-counted.
    if node.get("type") != "tool":
        return None

    state = node.get("state") if isinstance(node.get("state"), dict) else {}

    raw_input = None
    for key in _TOOL_INPUT_KEYS:
        if node.get(key) not in (None, ""):
            raw_input = node[key]
            break
    if raw_input is None:
        for key in _TOOL_INPUT_KEYS:
            if state.get(key) not in (None, ""):
                raw_input = state[key]
                break
    if isinstance(raw_input, str):
        try:
            raw_input = json.loads(raw_input)
        except (ValueError, TypeError):
            raw_input = {}
    if not isinstance(raw_input, dict):
        raw_input = {}

    kept = {}
    for key in _INPUT_KEEP:
        value = raw_input.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        kept[key] = value[:2000]

    return {
        "tool": tool,
        "name": _normalize_tool_name(tool),
        "input": kept,
        "known": _is_retrieval_tool(tool),
        "hits": [],
        "total": 0,
        "raw_event_type": event_type,
    }


def _collect_tool_names(node, names):
    """Append tool names found anywhere in ``node`` (order preserved).

    Any string under a ``tool`` key is collected -- retrieval or dev -- so the
    result pass can attach payloads to the generic records from the first pass.
    """
    budget = [200]

    def visit(candidate):
        value = candidate.get("tool")
        if isinstance(value, str) and value and value not in names:
            names.append(value)

    _walk(node, visit, budget)


def _payload_tool(node, events, index):
    """Pick the tool a result ``node`` belongs to, checking nearby events."""
    names = []
    _collect_tool_names(node, names)
    for offset in range(1, _COLOCATED_LINES + 1):
        for neighbor in (index - offset, index + offset):
            if 0 <= neighbor < len(events):
                _collect_tool_names(events[neighbor], names)
    return names


def _unwrap_payload(value):
    """Unwrap a FastMCP ``{"content": [{"type": "text", ...}]}`` envelope.

    FastMCP can spread one result across several ``text`` blocks (e.g. one hit
    per block), so every block is parsed as JSON and the parsed dicts/lists are
    combined into a single list, capped at :data:`_SEARCH_HITS`. Blocks that do
    not parse contribute their truncated text so no data is silently dropped.
    A single-block envelope keeps the original behavior -- the parsed value when
    it parses, else its raw text -- so SPARQL ``results.bindings`` and scalar
    payloads still normalize downstream. Non-envelope values are returned
    unchanged.
    """
    if not isinstance(value, dict):
        return value
    content = value.get("content")
    if not isinstance(content, list):
        return value
    texts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in _TEXT_BLOCK_TYPES:
            part = block.get("text")
            if isinstance(part, str) and part.strip():
                texts.append(part.strip())
    if not texts:
        return value
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except (ValueError, TypeError):
            return texts[0]
    combined = []
    for text in texts:
        try:
            item = json.loads(text)
        except (ValueError, TypeError):
            item = _truncate(text)
        if isinstance(item, list):
            combined.extend(item)
        else:
            combined.append(item)
    return combined[:_SEARCH_HITS]


def _normalize_payload(value, tool):
    """Return ``(hits, total)`` for a raw result payload, capped and truncated."""
    cap = _KG_HITS if tool == "query_kg" or tool.endswith("_query_kg") else _SEARCH_HITS
    bindings = _sparql_bindings(value)
    if bindings is not None:
        return [_truncate(item) for item in bindings[:cap]], len(bindings)
    if isinstance(value, list):
        return [_normalize_hit(item) for item in value[:cap]], len(value)
    text = _truncate(value)
    return ([text] if text else []), (1 if text else 0)


def _decode_output(raw):
    """Decode a logged tool ``output`` into its underlying Python value.

    The opencode ``trace-log`` plugin records ``output`` as a JSON string that
    may itself be JSON-encoded more than once (the raw string plus the
    enclosing record). Try ``json.loads`` up to two times, then run the
    existing :func:`_unwrap_payload` to dissolve FastMCP
    ``{"content": [{"type": "text", "text": ...}]}`` envelopes.
    """
    value = raw
    for _ in range(2):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            break
    return _unwrap_payload(value)


def _coerce_hit(item):
    """Parse a hit that is itself a JSON string encoding a dict/list."""
    if isinstance(item, str):
        stripped = item.strip()
        if stripped[:1] in ("{", "["):
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                return item
            if isinstance(parsed, (dict, list)):
                return parsed
    return item


def _hits_total_from_output(raw, tool):
    """Build ``(hits, total)`` from a logged ``output`` payload.

    SPARQL bindings are kept as dicts (only long string *values* are capped) so
    their columns fill instead of collapsing into one ``snippet`` blob. All
    other payloads reuse :func:`_normalize_payload`, then any hit that survived
    as a JSON string is parsed back into a dict/list.
    """
    value = _decode_output(raw)
    cap = _KG_HITS if tool == "query_kg" or tool.endswith("_query_kg") else _SEARCH_HITS
    bindings = _sparql_bindings(value)
    if bindings is not None:
        return [_normalize_hit(item) for item in bindings[:cap]], len(bindings)
    hits, total = _normalize_payload(value, tool)
    return [_normalize_hit(_coerce_hit(hit)) for hit in hits], total


def _parse_json_lines(text):
    """Parse JSON-lines ``text`` into a list of objects, skipping bad lines."""
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (ValueError, TypeError):
            continue
    return events


def _session_id_from_raw(text):
    """Return the first non-empty ``sessionID`` in JSON-lines ``text``, else ``None``.

    OpenCode nests the id either at the event top level (``event.sessionID``) or
    under ``event.part.sessionID``; the first non-empty one in file order wins.
    """
    for event in _parse_json_lines(text):
        if not isinstance(event, dict):
            continue
        part = event.get("part")
        for container in (event, part):
            if not isinstance(container, dict):
                continue
            value = container.get("sessionID")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _parse_events(text):
    """Parse JSON-lines ``text`` into ``(answer, sources)`` best-effort.

    Tool calls are collected first; a second pass attaches any co-located
    result payloads to the most recent matching, still-unmatched source.
    """
    events = _parse_json_lines(text)

    sources = []
    answer = ""
    for event in events:
        event_type = event.get("type") if isinstance(event, dict) else None
        budget = [200]
        best = [None, None]

        def visit(node, _event_type=event_type, _best=best):
            record = _tool_from_node(node, _event_type)
            if record is not None:
                sources.append(record)
            _consider_answer(node, _best)

        _walk(event, visit, budget)
        if best[1]:
            answer = best[1]

    matched = set()
    for index, event in enumerate(events):
        budget = [200]
        payloads = []

        def collect(node, _payloads=payloads):
            value = _result_value(node)
            if value is not None:
                _payloads.append(value)

        _walk(event, collect, budget)
        for value in payloads:
            value = _unwrap_payload(value)
            candidates = _payload_tool(event, events, index)
            for tool in candidates:
                for position in range(len(sources) - 1, -1, -1):
                    if position in matched:
                        continue
                    if sources[position].get("tool") == tool:
                        hits, total = _normalize_payload(value, tool)
                        sources[position]["hits"] = hits
                        sources[position]["total"] = total
                        matched.add(position)
                        break
                else:
                    continue
                break

    return answer, sources


def _diff_calls(path, since):
    """Read MCP call records appended to ``path`` after byte offset ``since``.

    Pure helper (no subprocess or network) so it can be exercised offline.
    Returns one record per parseable JSON line, in file order; malformed or
    non-record lines are skipped. Each record is
    ``{tool, name, input, hits, total[, error]}``.
    """
    try:
        path = Path(path)
        size = path.stat().st_size
    except OSError:
        return []
    if since is None or since < 0 or since > size:
        since = 0
    try:
        with path.open("rb") as fh:
            fh.seek(since)
            data = fh.read()
    except OSError:
        return []

    records = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(entry, dict):
            continue
        raw_tool = entry.get("tool")
        if not isinstance(raw_tool, str) or not raw_tool:
            continue
        # The trace-log plugin records the raw ``output`` payload; MCP_LOG
        # records already carry parsed ``hits``/``total``. Prefer ``output``
        # when present and fall back to the pre-computed fields otherwise.
        if isinstance(entry.get("output"), (str, dict, list)):
            hits, total = _hits_total_from_output(entry.get("output"), raw_tool)
        else:
            hits = entry.get("hits") if isinstance(entry.get("hits"), list) else []
            total = entry.get("total", 0)
        record = {
            "tool": raw_tool,
            "name": _normalize_tool_name(raw_tool),
            "input": entry.get("input") if isinstance(entry.get("input"), dict) else {},
            "hits": hits,
            "total": total,
        }
        if entry.get("error"):
            record["error"] = entry["error"]
        records.append(record)
    return records


def _read_new_calls(since_size):
    """Return MCP call records appended to ``config.MCP_LOG`` since ``since_size``.

    NOTE: this assumes a single user/session at a time. Any records another
    concurrent MCP client wrote in the same byte window would also be picked up
    and attributed to this run.
    """
    return _diff_calls(config.MCP_LOG, since_size)


def _record_from_trace(entry):
    """Map one ``trace-log`` plugin line to the shared source-record shape.

    ``args`` is the truncated JSON string written by the plugin; ``output`` is
    the raw tool result string (usually JSON, for MCP a ``{"content": [...]}``
    envelope). Malformed pieces degrade to empties so one bad line cannot drop
    the rest of the trace.
    """
    raw_tool = entry.get("tool")
    if not isinstance(raw_tool, str) or not raw_tool:
        return None

    args = entry.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, TypeError):
            args = {}
    if not isinstance(args, dict):
        args = {}

    kept = {}
    for key in _INPUT_KEEP:
        value = args.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        kept[key] = value[:2000]

    hits, total = _hits_total_from_output(entry.get("output"), raw_tool)

    return {
        "tool": raw_tool,
        "name": _normalize_tool_name(raw_tool),
        "input": kept,
        "hits": hits,
        "total": total,
        "callID": entry.get("callID", ""),
    }


def _load_trace_calls(session_id):
    """Return ``trace-log`` records matching ``session_id``, in file order.

    Pure helper reading ``<REPO_ROOT>/logs/tool_calls.jsonl`` (written by the
    opencode ``trace-log`` plugin). Returns ``[]`` when the session id is blank
    or the file is missing/unreadable, so callers can fall back.
    """
    if not session_id:
        return []
    path = config.REPO_ROOT / "logs" / "tool_calls.jsonl"
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    records = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(entry, dict) or entry.get("sessionID") != session_id:
            continue
        record = _record_from_trace(entry)
        if record is not None:
            records.append(record)
    return records


def run_agent(question: str, history=None, timeout: int = 300) -> dict:
    """Run ``opencode run --format json`` and return the answer and trace.

    Raises :class:`RuntimeError` with a short message when the ``opencode``
    binary is missing, exits non-zero, exceeds ``timeout`` seconds, or returns
    no usable answer text.
    """
    model = _resolve_model()
    prompt = _build_prompt(question, history)
    argv = [
        "opencode",
        "run",
        "--model",
        model,
        "--agent",
        "sales",
        "--format",
        "json",
        prompt,
    ]

    # Single-user assumption: remember where the shared MCP log ended before the
    # run so we can attribute only the calls this run appended. A concurrent
    # session's records in the same window would be picked up too.
    try:
        start_size = config.MCP_LOG.stat().st_size
    except OSError:
        start_size = 0

    try:
        proc = subprocess.run(
            argv,
            cwd=str(config.REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("opencode executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"opencode run timed out after {timeout}s") from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        detail = f": {stderr[:500]}" if stderr else ""
        raise RuntimeError(f"opencode run failed (exit {proc.returncode}){detail}")

    raw = proc.stdout or ""
    answer, event_sources = _parse_events(raw)

    # Preferred: the opencode "trace-log" plugin appends one line per tool call,
    # tagged with the session id, to logs/tool_calls.jsonl. When at least one
    # line matches this run's session id those records are authoritative (in file
    # order) and replace the fallbacks below. Otherwise fall back to the MCP
    # server's ground-truth call records written to config.MCP_LOG while the
    # subprocess runs; if logging was unavailable (zero new records), keep the
    # old behavior of the adjacency-guessed event payloads.
    trace_sources = _load_trace_calls(_session_id_from_raw(raw))
    if trace_sources:
        sources = trace_sources
    else:
        log_sources = _read_new_calls(start_size)
        sources = log_sources if log_sources else event_sources

    if not answer:
        kept = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                json.loads(stripped)
                continue
            except (ValueError, TypeError):
                pass
            kept.append(stripped)
        answer = "\n".join(kept).strip()[:8000]

    if not answer:
        raise RuntimeError("opencode returned no answer text")

    return {
        "answer": answer,
        "sources": sources,
        "meta": {
            "engine": _ENGINE,
            "model": model,
            "command": argv,
            "steps": len(sources),
            "graphdb_url": config.GRAPHDB_URL,
            "graphdb_repo": config.GRAPHDB_REPO,
            "iris": _extract_iris(answer),
        },
    }
