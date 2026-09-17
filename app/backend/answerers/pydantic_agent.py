"""PydanticAI answerer (ANSWERER=pydantic): OpenRouter via an OpenAI-compatible endpoint.

No provider call is made at import time: the model/client is constructed with a
deferred key when :data:`app.config.PYDANTIC_API_KEY` is empty, so importing this
module only reads ``system.md`` and the installed package. Live calls happen only
inside :func:`answer`.

Version note: the brief names ``OpenAIModel``; the installed PydanticAI 2.43.0
renamed it to ``OpenAIChatModel`` (``OpenAIModel`` no longer exists). The import
below prefers the new name and falls back to the old one for ``>=0.40`` installs.
``OpenAIProvider(api_key="")`` raises, so an empty key is passed as ``None`` to
keep construction offline; :func:`answer` raises ``RuntimeError`` instead.

History note: prior turns are converted to PydanticAI ``ModelMessage`` objects
best-effort; any turn that fails to convert is skipped rather than failing the run.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

try:  # PydanticAI >= 1.0 / 2.x
    from pydantic_ai.models.openai import OpenAIChatModel as _OpenAIModel
except ImportError:  # pragma: no cover - older pydantic-ai
    from pydantic_ai.models.openai import OpenAIModel as _OpenAIModel  # type: ignore

from pydantic_ai.providers.openai import OpenAIProvider

from app import config
from app.backend.trace_helpers import (
    extract_iris as _extract_iris,
    normalize_hit as _normalize_hit,
    sparql_bindings as _sparql_bindings,
    truncate as _truncate,
)
from app.backend.schemas import ChatResponse
from app.mcp.guards import MAX_ROWS, MAX_TOP_K, SPARQL_TIMEOUT, assert_readonly, clamp_top_k
from app.retrieval import keyword, kg, transcripts, vector

logger = logging.getLogger(__name__)

_ENGINE = "pydantic"
_SYSTEM_PROMPT = Path(__file__).resolve().parents[2] / "agent" / "system.md"

# Trace-shaping caps, matching app.agent.opencode: hits lists capped at 5 and the
# longest string kept per hit is 500 chars.
_MAX_HITS = 5
# Input keys kept in the source record (same set the MCP call log keeps).
_INPUT_KEEP = ("sparql", "query", "top_k", "transcript_id")
_INPUT_CHARS = 2000

# PydanticAI transport prefixes that are redundant for an OpenAI-compatible
# client. OpenRouter org namespaces (e.g. "meta/") are NOT stripped because the
# hosted model id needs them.
_PROVIDER_PREFIXES = ("openai/", "openai-chat/", "openai-responses/", "gateway/")


def _strip_provider_prefix(model: str) -> str:
    """Drop a leading PydanticAI transport prefix such as ``openai/``."""
    name = (model or "").strip()
    for prefix in _PROVIDER_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


# --- Plain tools (M2 retrieval wrappers, offline-safe except live KG/vector) ---
def query_kg(sparql: str) -> dict:
    """Run a read-only SPARQL query against the GraphDB repository."""
    try:
        assert_readonly(sparql)
    except ValueError as exc:
        return {"error": str(exc)}
    try:
        return kg.run_sparql(sparql, timeout=SPARQL_TIMEOUT, max_rows=MAX_ROWS)
    except RuntimeError as exc:
        return {"error": str(exc)}


def semantic_search(query: str, top_k: int = 3) -> list:
    """Return transcript chunks semantically similar to ``query``."""
    return vector.semantic_search(query, clamp_top_k(top_k, hi=MAX_TOP_K))


def keyword_search(query: str, top_k: int = 3) -> list:
    """Return transcript chunks ranked by BM25 keyword relevance to ``query``."""
    return keyword.keyword_search(query, clamp_top_k(top_k, hi=MAX_TOP_K))


def get_transcript(transcript_id: str) -> dict:
    """Return one transcript by id, or an error dict when it is unknown."""
    try:
        return transcripts.get_transcript(transcript_id)
    except KeyError as exc:
        return {"error": str(exc)}


def _build_agent() -> Agent:
    provider = OpenAIProvider(
        base_url=config.PYDANTIC_BASE_URL,
        api_key=config.PYDANTIC_API_KEY or None,
    )
    model = _OpenAIModel(_strip_provider_prefix(config.PYDANTIC_MODEL), provider=provider)

    system_prompt = _SYSTEM_PROMPT.read_text(encoding="utf-8")
    # Append the competency SPARQL examples (config.COMPETENCY_QUERIES); a
    # missing or empty file degrades gracefully to the bare system prompt.
    try:
        examples = config.COMPETENCY_QUERIES.read_text(encoding="utf-8").strip()
    except OSError:
        examples = ""
    if examples:
        system_prompt = (
            f"{system_prompt}\n\n"
            f"## SPARQL examples (follow these patterns)\n\n{examples}\n"
        )

    return Agent(
        model,
        system_prompt=system_prompt,
        tools=[query_kg, semantic_search, keyword_search, get_transcript],
    )


_agent = _build_agent()


# --- History / source shaping -------------------------------------------------
def _history_messages(history):
    """Convert ``[{"role": ..., "content": ...}]`` into PydanticAI messages."""
    if not history:
        return None
    messages = []
    for turn in history:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "user")).strip().lower() or "user"
        content = turn.get("content")
        if content is None:
            continue
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)
        try:
            if role == "assistant":
                messages.append(ModelResponse(parts=[TextPart(content=content)]))
            elif role == "system":
                messages.append(ModelRequest(parts=[SystemPromptPart(content=content)]))
            else:
                messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        except Exception:  # pragma: no cover - defensive, version friction
            logger.warning("skipping unconvertible history turn: role=%r", role)
    return messages or None


def _hits_total(value):
    """Return ``(hits, total)`` for a tool return value, capped and truncated."""
    bindings = _sparql_bindings(value)
    if bindings is not None:
        return [_normalize_hit(item) for item in bindings[:_MAX_HITS]], len(bindings)
    if isinstance(value, list):
        return [_normalize_hit(item) for item in value[:_MAX_HITS]], len(value)
    if isinstance(value, dict):
        if "error" in value:
            return [], 0
        return [_normalize_hit(value)], 1
    text = _truncate(value)
    return ([text] if text else []), (1 if text else 0)


def _kept_input(args) -> dict:
    """Keep only trace-relevant tool input keys, each capped at 2000 chars.

    PydanticAI hands ``ToolCallPart.args`` to us as a JSON *string*, not a dict,
    so decode it first (falling back to ``{}``) before filtering keys.
    """
    kept = {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, TypeError):
            args = {}
    if not isinstance(args, dict):
        return kept
    for key in _INPUT_KEEP:
        value = args.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
        kept[key] = value[:_INPUT_CHARS]
    return kept


def _plain_tool_name(name) -> str:
    """Normalize a tool name to its plain, un-namespaced form."""
    plain = str(name or "").strip()
    for sep in (":", "/"):
        if sep in plain:
            plain = plain.rsplit(sep, 1)[-1]
    return plain


def _sources_from_messages(messages) -> list:
    """Build one source record per tool call, pairing calls with their results."""
    returns = {}
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart):
                returns[part.tool_call_id] = part

    sources = []
    for message in messages:
        for part in getattr(message, "parts", []):
            if not isinstance(part, ToolCallPart):
                continue
            result = returns.get(part.tool_call_id)
            if result is not None:
                payload = result.content
                hits, total = _hits_total(payload)
            else:
                payload = None
                hits, total = [], 0
            record = {
                "tool": _plain_tool_name(part.tool_name),
                "input": _kept_input(part.args),
                "hits": hits,
                "total": total,
            }
            if isinstance(payload, dict) and "error" in payload:
                record["error"] = str(payload["error"])
                record["ok"] = False
            else:
                record["ok"] = True
            sources.append(record)
    return sources


def answer(question: str, history=None) -> ChatResponse:
    """Run the PydanticAI agent and adapt its result to ``ChatResponse``."""
    if not config.PYDANTIC_API_KEY:
        raise RuntimeError("PYDANTIC_API_KEY is not set")

    logger.info("question=%r model=%s", question[:300], config.PYDANTIC_MODEL)
    try:
        result = _agent.run_sync(question, message_history=_history_messages(history))
    except Exception as exc:
        logger.warning("pydantic-ai run failed: %s", exc)
        raise RuntimeError(f"pydantic-ai run failed: {exc}") from exc

    answer_text = result.output
    sources = _sources_from_messages(result.new_messages())
    return ChatResponse(
        answer=answer_text,
        sources=sources,
        meta={
            "engine": _ENGINE,
            "model": config.PYDANTIC_MODEL,
            "steps": len(sources),
            "graphdb_url": config.GRAPHDB_URL,
            "graphdb_repo": config.GRAPHDB_REPO,
            "iris": _extract_iris(answer_text),
        },
    )
