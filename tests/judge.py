"""LLM-as-judge helper for live evaluation tests.

This module is deliberately NOT named ``test_*`` so pytest never collects it;
it is imported by ``tests/test_judge_live.py``.

:func:`judge` calls an OpenRouter chat-completions endpoint with a strict
grading prompt and returns a normalized ``{score, verdict, missing, reason}``
dict. Any HTTP or parsing failure raises :class:`RuntimeError` so the caller
can decide whether to skip (judge infrastructure unavailable) or fail.

The model is read from the ``JUDGE_MODEL`` environment variable at call time;
no model id is hardcoded, and a missing one is a hard :class:`RuntimeError`.
"""
from __future__ import annotations

import json
import os

import requests

from app import config

_SYSTEM_PROMPT = (
    "You are a strict, literal grader for a question-answering system. "
    "Score the CANDIDATE ANSWER on factual overlap with the REFERENCE FACTS "
    "only. Ignore style, tone, verbosity, hedging and formatting. A fact "
    "counts only if the candidate asserts it and it matches the reference. "
    "Deduct for contradictions and for missing facts. Return ONLY a JSON "
    'object with exactly these keys: "score" (integer 0-100), "verdict" '
    '("pass" or "fail"), "missing" (array of short strings), and "reason" '
    '(short string). Set verdict to "pass" only when the answer is factually '
    'faithful and covers the reference facts; otherwise "fail".'
)


def _build_user_content(question, reference_facts, candidate_answer) -> str:
    return (
        f"QUESTION:\n{question}\n\n"
        f"REFERENCE FACTS (ground truth):\n{reference_facts}\n\n"
        f"CANDIDATE ANSWER (to grade):\n{candidate_answer}\n\n"
        "Return only the JSON object described in the system prompt."
    )


def judge(question, reference_facts, candidate_answer, model=None, timeout=30) -> dict:
    """Grade ``candidate_answer`` against ``reference_facts`` with an LLM.

    Returns ``{"score": int, "verdict": "pass"|"fail", "missing": list,
    "reason": str}``. Raises :class:`RuntimeError` if ``JUDGE_MODEL`` is unset
    or if the HTTP request or JSON parsing fails.
    """
    model = model or os.environ.get("JUDGE_MODEL", "")
    if not model:
        raise RuntimeError("JUDGE_MODEL is not set")

    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_content(
                    question, reference_facts, candidate_answer
                ),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            config.OPENROUTER_URL, headers=headers, json=payload, timeout=timeout
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"judge request failed: {exc}") from exc

    try:
        envelope = response.json()
        content = envelope["choices"][0]["message"]["content"]
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("judge content is not a JSON object")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"judge response could not be parsed: {exc}") from exc

    try:
        score = int(round(float(data["score"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"judge score missing or invalid: {exc}") from exc
    score = max(0, min(100, score))

    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("pass", "fail"):
        verdict = "pass" if score >= 50 else "fail"

    missing = data.get("missing")
    if not isinstance(missing, list):
        missing = []
    missing = [str(item) for item in missing]

    reason = data.get("reason")
    reason = reason if isinstance(reason, str) else str(reason or "")

    return {
        "score": score,
        "verdict": verdict,
        "missing": missing,
        "reason": reason,
    }
