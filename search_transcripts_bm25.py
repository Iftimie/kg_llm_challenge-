"""Lexical transcript search with BM25. Run: python search_transcripts_bm25.py "pricing negotiation" """
import csv
import re
import sys

from rank_bm25 import BM25Okapi

QUESTIONS = [
    "Which transcript mentions SSO and data residency?",
    "Who talked about procurement expecting a better price?",
    "Which customer mentioned forecast accuracy?",
    "Which conversation mentions model governance?",
    "Which transcript mentions a wind farm?",
    "Who said the product isn't the issue?",
    "Which customer talked about fragmented analytics pipelines?",
    "Which conversation mentions three factories?",
    "Who was concerned about authentication and where data is stored?",
    "Which customer wanted proof that the solution improves operational results?",
    "Who wanted to expand deployment to several locations?",
    "Which customer had concerns about internal spending restrictions?",
]


def tokenize(text: str) -> list:
    return re.findall(r"\w+", text.lower())


def search(bm25, query: str, top_n: int = 3) -> list:
    scores = bm25.get_scores(tokenize(query))
    return sorted(range(len(rows)), key=lambda j: scores[j], reverse=True)[:top_n], scores


with open("mock_crm_dataset/transcripts.csv", newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

corpus = [tokenize(r["transcript"]) for r in rows]
bm25 = BM25Okapi(corpus)

if len(sys.argv) > 1 and sys.argv[1] == "--all":
    for q in QUESTIONS:
        top, scores = search(bm25, q, top_n=1)
        print(f"{rows[top[0]]['transcript_id']}  score={scores[top[0]]:.4f}  <- {q}")
    sys.exit()

query = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()
top, scores = search(bm25, query)

for i in top:
    r = rows[i]
    meta = {"deal_id": r["deal_id"], "account_id": r["account_id"],
            "activity_date": r["activity_date"], "channel": r["channel"]}
    print(f"{r['transcript_id']}  score={scores[i]:.4f}  {meta}")
    print(f"  {r['transcript'][:200]}...")
    print()
