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
import re
import subprocess
from pathlib import Path

from app import config

_ENGINE = "agent"
_SYSTEM_PROMPT = Path(__file__).with_name("system.md")
_OPENCODE_PROVIDER = "openrouter"

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
_HIT_CHARS = 500
_COLOCATED_LINES = 3

_IRI_RE = re.compile(r"https?://[^\s<>\"'`]+")


def _resolve_model() -> str:
    """Return an OpenCode ``provider/model`` id, defaulting to OpenRouter."""
    model = (config.OPENROUTER_MODEL or "").strip()
    prefix = f"{_OPENCODE_PROVIDER}/"
    if model.startswith(prefix):
        return model
    return f"{prefix}{model}"


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


def _truncate(value, limit=_HIT_CHARS):
    """Render ``value`` as a string no longer than ``limit`` characters."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    return text[:limit]


def _normalize_hit(item, limit=_HIT_CHARS):
    """Keep dict hits as dicts; truncate only long string values.

    List payloads (keyword/vector search) carry dict hits whose ``id``/``score``
    columns the UI renders directly. Stringifying the whole item would blank
    those columns, so dicts are preserved with their keys intact.
    """
    if isinstance(item, dict):
        return {
            key: (value[:limit] if isinstance(value, str) and len(value) > limit else value)
            for key, value in item.items()
        }
    return _truncate(item, limit)


def _sparql_bindings(value):
    """Return ``results.bindings`` if ``value`` looks like SPARQL JSON."""
    node = value
    if isinstance(node, str):
        stripped = node.strip()
        if not stripped.startswith("{"):
            return None
        try:
            node = json.loads(stripped)
        except (ValueError, TypeError):
            return None
    if not isinstance(node, dict):
        return None
    results = node.get("results")
    if isinstance(results, dict) and isinstance(results.get("bindings"), list):
        return results.get("bindings")
    if isinstance(node.get("bindings"), list):
        return node.get("bindings")
    return None


def _unwrap_payload(value):
    """Unwrap a FastMCP ``{"content": [{"type": "text", ...}]}`` envelope.

    Each text block is parsed as JSON and the first parse wins; if none parse,
    the joined text is used. Non-envelope values are returned unchanged so the
    existing SPARQL/list/scalar normalization still applies downstream.
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
    for text in texts:
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            continue
    return "\n".join(texts)


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


def _parse_events(text):
    """Parse JSON-lines ``text`` into ``(answer, sources)`` best-effort.

    Tool calls are collected first; a second pass attaches any co-located
    result payloads to the most recent matching, still-unmatched source.
    """
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (ValueError, TypeError):
            continue

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


def _extract_iris(text, limit=20):
    """Pull absolute http(s) IRIs out of ``text``, deduped in order."""
    seen = set()
    iris = []
    for match in _IRI_RE.findall(text or ""):
        iri = match.rstrip(".,;:)]`")
        if iri and iri not in seen:
            seen.add(iri)
            iris.append(iri)
            if len(iris) >= limit:
                break
    return iris


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
        record = {
            "tool": raw_tool,
            "name": _normalize_tool_name(raw_tool),
            "input": entry.get("input") if isinstance(entry.get("input"), dict) else {},
            "hits": entry.get("hits") if isinstance(entry.get("hits"), list) else [],
            "total": entry.get("total", 0),
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

    # The server writes ground-truth call records to config.MCP_LOG while the
    # subprocess runs; prefer them over the adjacency-guessed event payloads.
    # If logging was unavailable (zero new records), keep the old behavior.
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
