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
import logging
import os
import re
import tempfile

import requests

from app import config
from app.backend.schemas import ChatResponse

logger = logging.getLogger(__name__)

# Timeouts (seconds): generous for LLM generation, short for the local store.
_LLM_TIMEOUT = 600
_GRAPHDB_TIMEOUT = 60


def clean(text: str) -> str:
    """Strip code fences and wrap bare PREFIX IRIs (LLMs often drop the <>)."""
    text = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("```")).strip()
    return re.sub(r"(?m)^(\s*PREFIX\s+[\w-]+:\s*)(?![<\"])([^\s<>]+)\s*$", r"\1<\2>", text)


def _extract_iris(*texts, limit=20):
    """Pull absolute http(s) IRIs out of arbitrary text, deduped in order."""
    seen = set()
    iris = []
    for text in texts:
        for match in re.findall(r"https?://[^\s<>\"']+", text or ""):
            iri = match.rstrip(".,;)]`")
            if iri and iri not in seen:
                seen.add(iri)
                iris.append(iri)
                if len(iris) >= limit:
                    return iris
    return iris


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
        logger.warning("OpenRouter request failed: %s", exc)
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

    if r.status_code >= 400:
        logger.warning("OpenRouter error %s: %s", r.status_code, r.text[:1000])
        raise RuntimeError(f"OpenRouter error {r.status_code}: {r.text[:1000]}")

    try:
        return r.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Unexpected OpenRouter response: %s", exc)
        raise RuntimeError(f"Unexpected OpenRouter response: {exc}") from exc


def _run_sparql(sparql: str) -> dict:
    """Execute SPARQL against GraphDB and return the JSON results document."""
    repo_url = f"{config.GRAPHDB_URL}/repositories/{config.GRAPHDB_REPO}"
    try:
        q = requests.get(
            repo_url,
            params={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
            timeout=_GRAPHDB_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("GraphDB is unreachable at %s: %s", config.GRAPHDB_URL, exc)
        raise RuntimeError(f"GraphDB is unreachable at {config.GRAPHDB_URL}: {exc}") from exc

    if q.status_code >= 400:
        logger.warning("GraphDB error %s: %s", q.status_code, q.text[:1000])
        raise RuntimeError(f"GraphDB error {q.status_code}: {q.text[:1000]}")

    try:
        return q.json()
    except ValueError as exc:
        logger.warning("GraphDB returned a non-JSON response")
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

    logger.info("question=%r model=%s", question[:300], config.OPENROUTER_MODEL)

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
    logger.info("generated SPARQL: %r", sparql)

    # Per-request scratch space instead of the shared qa/ directory.
    # KG_DEBUG keeps the directory around for inspection instead of deleting it.
    kg_debug = os.environ.get("KG_DEBUG", "").lower() in ("1", "true", "yes")
    if kg_debug:
        tmp = tempfile.mkdtemp(prefix="kg_baseline_")
        tmp_cm = None
        logger.info("KG_DEBUG enabled, keeping temp dir: %s", tmp)
    else:
        tmp_cm = tempfile.TemporaryDirectory(prefix="kg_baseline_")
        tmp = tmp_cm.name

    try:
        _write(os.path.join(tmp, "question.txt"), question + "\n")
        _write(os.path.join(tmp, "sparql.rq"), sparql + "\n")

        logger.info("GraphDB repo URL: %s/repositories/%s", config.GRAPHDB_URL, config.GRAPHDB_REPO)
        results = _run_sparql(sparql)
        _write(os.path.join(tmp, "results.json"), json.dumps(results, indent=2))
        bindings = results.get("results", {}).get("bindings", [])
        row_count = len(bindings)
        sample = bindings[:5]
        logger.info("row_count=%s", row_count)

        answer_prompt = f"""Answer the user question using ONLY the SPARQL results below.
If the results are empty, say so plainly instead of inventing facts.
Style rules:
- Lead with a short human answer (1-2 sentences a salesperson can act on).
- Then one line: "How I checked: I ran a KG query (N rows) ..." (replace N with the row count).
- Refer to entities as short labels in markdown links, e.g. [Deal D007](IRI), [Transcript T007](IRI). Never paste bare https://... IRIs in prose.
- Write predicates as plain words (decision criterion, supported by, speaker), not IRIs. No IRI dumps.
- Keep it concise and grounded, and cite quotes as "quote" — speaker, transcript.

USER QUESTION:
{question}

SPARQL QUERY USED:
{sparql}

SPARQL RESULTS (JSON):
{json.dumps(results)}

Final answer:"""

        final_answer = _ask_openrouter(api_key, answer_prompt)
        _write(os.path.join(tmp, "answer.txt"), final_answer + "\n")
        iris = _extract_iris(final_answer, sparql, json.dumps(sample))
        logger.info("answer length=%s", len(final_answer))
    finally:
        if tmp_cm is not None:
            tmp_cm.cleanup()

    return ChatResponse(
        answer=final_answer,
        sources=[{"sparql": sparql, "row_count": row_count, "sample": sample, "iris": iris}],
        meta={
            "engine": "baseline",
            "sparql": sparql,
            "model": config.OPENROUTER_MODEL,
            "graphdb_url": config.GRAPHDB_URL,
            "graphdb_repo": config.GRAPHDB_REPO,
        },
    )
