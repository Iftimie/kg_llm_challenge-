"""Step 1: user question -> LLM -> SPARQL -> GraphDB results. Run: python ask_step1.py "your question" """
import json
import os
import re
import sys

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta/muse-spark-1.3-contributor"
GRAPHDB = "http://127.0.0.1:7200"
REPO = "sales-kg"


def clean(text: str) -> str:
    text = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("```")).strip()
    # safety net: wrap bare PREFIX IRIs in <> (LLMs often drop them)
    return re.sub(r"(?m)^(\s*PREFIX\s+[\w-]+:\s*)(?![<\"])([^\s<>]+)\s*$", r"\1<\2>", text)


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()
    question = open(arg, encoding="utf-8").read().strip() if os.path.isfile(arg) else arg
    os.makedirs("qa", exist_ok=True)

    with open("sales_kg_ontology_v1.ttl", encoding="utf-8") as f:
        ontology = f.read()
    with open("competency_queries.txt", encoding="utf-8") as f:
        examples = f.read()

    prompt = f"""You translate a user question into a SPARQL query over a Sales Knowledge Graph.
Use only the ontology below. Follow the style of the SPARQL examples.

ONTOLOGY:
{ontology}

SPARQL EXAMPLES:
{examples}

USER QUESTION:
{question}

Return ONLY the SPARQL query, no code fences, no explanation."""

    api_key = os.environ["OPENROUTER_API_KEY"]  # fails fast if missing
    r = requests.post(OPENROUTER_URL,
                      headers={"Authorization": f"Bearer {api_key}"},
                      json={"model": MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0},
                      timeout=600)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        print("OpenRouter error:", r.status_code, r.text[:1000])
        raise
    sparql = clean(r.json()["choices"][0]["message"]["content"])

    with open(os.path.join("qa", "question.txt"), "w", encoding="utf-8") as f:
        f.write(question + "\n")
    with open(os.path.join("qa", "sparql.rq"), "w", encoding="utf-8") as f:
        f.write(sparql + "\n")
    print(sparql)

    q = requests.get(f"{GRAPHDB}/repositories/{REPO}", params={"query": sparql},
                     headers={"Accept": "application/sparql-results+json"}, timeout=60)
    q.raise_for_status()
    results = q.json()
    with open(os.path.join("qa", "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    n = len(results.get("results", {}).get("bindings", []))
    print(f"\n{n} rows -> qa/results.json")


if __name__ == "__main__":
    main()
