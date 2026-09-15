"""Baseline answerer: question -> LLM -> SPARQL -> GraphDB -> LLM -> answer.

Behavior-preserving extraction of the top-level ``ask_step1.py`` and
``ask_step2.py`` scripts. The only intentional change is that the intermediate
``question.txt`` / ``sparql.rq`` / ``results.json`` / ``answer.txt`` files are
written to a per-request ``tempfile.TemporaryDirectory`` instead of the shared
``qa/`` directory, so concurrent requests cannot clobber each other.

External services are configured through :mod:`app.config` and called with
``requests`` only. Failures are surfaced as ``RuntimeError`` with a short,
human-readable message (no internal traceback leaks).
"""
import json
import os
import re
import tempfile

import requests

from app import config
from app.backend.schemas import ChatResponse

# Timeouts (seconds): generous for LLM generation, short for the local store.
_LLM_TIMEOUT = 600
_GRAPHDB_TIMEOUT = 60


def clean(text: str) -> str:
    """Strip code fences and wrap bare PREFIX IRIs (LLMs often drop the <>)."""
    text = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("```")).strip()
    return re.sub(r"(?m)^(\s*PREFIX\s+[\w-]+:\s*)(?![<\"])([^\s<>]+)\s*$", r"\1<\2>", text)


def _read(path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _ask_openrouter(api_key: str, prompt: str) -> str:
    """POST a single prompt to OpenRouter and return the assistant message."""
    try:
        r = requests.post(
            config.OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": config.OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=_LLM_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

    if r.status_code >= 400:
        raise RuntimeError(f"OpenRouter error {r.status_code}: {r.text[:1000]}")

    try:
        return r.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response: {exc}") from exc


def _run_sparql(sparql: str) -> dict:
    """Execute SPARQL against GraphDB and return the JSON results document."""
    try:
        q = requests.get(
            f"{config.GRAPHDB_URL}/repositories/{config.GRAPHDB_REPO}",
            params={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
            timeout=_GRAPHDB_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"GraphDB is unreachable at {config.GRAPHDB_URL}: {exc}") from exc

    if q.status_code >= 400:
        raise RuntimeError(f"GraphDB error {q.status_code}: {q.text[:1000]}")

    try:
        return q.json()
    except ValueError as exc:
        raise RuntimeError("GraphDB returned a non-JSON response") from exc


def answer(question: str, history=None) -> ChatResponse:
    """Translate ``question`` to SPARQL, run it, and summarize the rows.

    ``history`` is accepted for API symmetry but the baseline flow (like the
    original scripts) is single-turn and does not use it.
    """
    ontology = _read(config.ONTOLOGY_PATH)
    examples = _read(config.COMPETENCY_QUERIES)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    sparql_prompt = f"""You translate a user question into a SPARQL query over a Sales Knowledge Graph.
Use only the ontology below. Follow the style of the SPARQL examples.

ONTOLOGY:
{ontology}

SPARQL EXAMPLES:
{examples}

USER QUESTION:
{question}

Return ONLY the SPARQL query, no code fences, no explanation."""

    sparql = clean(_ask_openrouter(api_key, sparql_prompt))

    # Per-request scratch space instead of the shared qa/ directory.
    with tempfile.TemporaryDirectory(prefix="kg_baseline_") as tmp:
        _write(os.path.join(tmp, "question.txt"), question + "\n")
        _write(os.path.join(tmp, "sparql.rq"), sparql + "\n")

        results = _run_sparql(sparql)
        _write(os.path.join(tmp, "results.json"), json.dumps(results, indent=2))
        row_count = len(results.get("results", {}).get("bindings", []))

        answer_prompt = f"""Answer the user question using ONLY the SPARQL results below.
If the results are empty, say so plainly instead of inventing facts.

USER QUESTION:
{question}

SPARQL QUERY USED:
{sparql}

SPARQL RESULTS (JSON):
{json.dumps(results)}

Final answer:"""

        final_answer = _ask_openrouter(api_key, answer_prompt)
        _write(os.path.join(tmp, "answer.txt"), final_answer + "\n")

    return ChatResponse(
        answer=final_answer,
        sources=[{"sparql": sparql, "row_count": row_count}],
        meta={
            "engine": "baseline",
            "sparql": sparql,
            "model": config.OPENROUTER_MODEL,
        },
    )
