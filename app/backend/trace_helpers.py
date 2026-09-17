"""Shared trace-shaping helpers used by both answerers (opencode + pydantic).

Single source of truth for rendering tool hits, SPARQL bindings and answer IRIs
into the compact source records the UI renders. Stdlib only so
``app.agent.opencode`` can stay stdlib-only.
"""
from __future__ import annotations

import json
import re

# Absolute http(s) IRIs, excluding whitespace, angle brackets, quotes and the
# backtick (which OpenCode emits around markdown links).
_IRI_RE = re.compile(r"https?://[^\s<>\"'`]+")

DEFAULT_LIMIT = 500


def truncate(value, limit: int = DEFAULT_LIMIT) -> str:
    """Render ``value`` as a string no longer than ``limit`` characters."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    return text[:limit]


def normalize_hit(item, limit: int = DEFAULT_LIMIT):
    """Keep dict hits as dicts (truncating long string values); stringify the rest.

    List payloads (keyword/vector search) carry dict hits whose ``id``/``score``
    columns the UI renders directly; stringifying the whole item would blank
    those columns, so dicts are preserved with their keys intact.
    """
    if isinstance(item, dict):
        return {
            key: (value[:limit] if isinstance(value, str) and len(value) > limit else value)
            for key, value in item.items()
        }
    return truncate(item, limit)


def sparql_bindings(value):
    """Return ``results.bindings`` if ``value`` looks like SPARQL JSON, else None."""
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


def extract_iris(*texts, limit: int = 20) -> list:
    """Pull absolute http(s) IRIs out of arbitrary text, deduped in order."""
    seen = set()
    iris = []
    for text in texts:
        for match in _IRI_RE.findall(text or ""):
            iri = match.rstrip(".,;:)]`\"")
            if iri and iri not in seen:
                seen.add(iri)
                iris.append(iri)
                if len(iris) >= limit:
                    return iris
    return iris
