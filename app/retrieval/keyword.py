"""Lexical transcript search with BM25Okapi (offline, no service required)."""
import csv
import re

from rank_bm25 import BM25Okapi

from app import config

_CSV_NAME = "transcripts.csv"
_cache = None


def tokenize(text: str) -> list:
    return re.findall(r"\w+", text.lower())


def reset_cache():
    global _cache
    _cache = None


def _load():
    """Return ``(rows, bm25)`` from the CSV, memoized on first use."""
    global _cache
    if _cache is None:
        path = config.DATA_DIR / _CSV_NAME
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        corpus = [tokenize(r.get("transcript", "")) for r in rows]
        _cache = (rows, BM25Okapi(corpus))
    return _cache


def keyword_search(query, top_k=3) -> list:
    """Return the top chunks as ``{id, score, metadata, snippet}``."""
    rows, bm25 = _load()
    top_k = min(max(int(top_k), 1), 10)

    scores = bm25.get_scores(tokenize(query))
    order = sorted(range(len(rows)), key=lambda j: scores[j], reverse=True)[:top_k]

    results = []
    for i in order:
        r = rows[i]
        metadata = {
            "deal_id": r["deal_id"],
            "account_id": r["account_id"],
            "activity_date": r["activity_date"],
            "channel": r["channel"],
        }
        results.append(
            {
                "id": r["transcript_id"],
                "score": float(scores[i]),
                "metadata": metadata,
                "snippet": (r.get("transcript") or "")[:200],
            }
        )
    return results
