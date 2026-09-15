"""Step 2: GraphDB results -> LLM -> final answer. Run: python ask_step2.py"""
import json
import os

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta/muse-spark-1.3-contributor"


def main() -> None:
    with open(os.path.join("qa", "question.txt"), encoding="utf-8") as f:
        question = f.read()
    with open(os.path.join("qa", "sparql.rq"), encoding="utf-8") as f:
        sparql = f.read()
    with open(os.path.join("qa", "results.json"), encoding="utf-8") as f:
        results = json.load(f)

    prompt = f"""Answer the user question using ONLY the SPARQL results below.
If the results are empty, say so plainly instead of inventing facts.

USER QUESTION:
{question}

SPARQL QUERY USED:
{sparql}

SPARQL RESULTS (JSON):
{json.dumps(results)}

Final answer:"""

    api_key = os.environ["OPENROUTER_API_KEY"]  # fails fast if missing
    r = requests.post(OPENROUTER_URL,
                      headers={"Authorization": f"Bearer {api_key}"},
                      json={"model": MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0},
                      timeout=600)
    r.raise_for_status()
    
    answer = r.json()["choices"][0]["message"]["content"]

    with open(os.path.join("qa", "answer.txt"), "w", encoding="utf-8") as f:
        f.write(answer + "\n")
    print(answer)


if __name__ == "__main__":
    main()
