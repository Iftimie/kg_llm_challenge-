"""Step 2: GraphDB results -> LLM -> final answer. Run: python ask_step2.py"""
import json
import os

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3.5:9b-agent"


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

    r = requests.post(OLLAMA_URL,
                      json={"model": MODEL, "prompt": prompt, "stream": False,
                            "options": {"temperature": 0, "num_ctx": 32768}},
                      timeout=600)
    r.raise_for_status()
    answer = r.json()["response"].strip()

    with open(os.path.join("qa", "answer.txt"), "w", encoding="utf-8") as f:
        f.write(answer + "\n")
    print(answer)


if __name__ == "__main__":
    main()
