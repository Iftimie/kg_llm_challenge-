"""Extract KG triples from transcripts with local Ollama model. Run: python extract.py [limit]"""
import csv
import os
import sys

import requests
from rdflib import Graph, Namespace, URIRef

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3.5:35b"

CRM = Namespace("https://example.org/sales-kg/")
RES = Namespace("https://example.org/sales-kg/resource/")


def crm_context(kg: Graph, deal_id: str, account_id: str) -> str:
    """Small Turtle snippet of the deal, account, contacts, products — canonical URIs from kg.nt."""
    ctx = Graph()
    ctx.bind("crm", CRM)
    ctx.bind("res", RES)
    deal = RES[f"Deal_{deal_id}"]
    for triple in kg.triples((deal, None, None)):
        ctx.add(triple)
        if isinstance(triple[2], URIRef):  # one hop: account, product, salesrep, outcome
            for t2 in kg.triples((triple[2], None, None)):
                ctx.add(t2)
    account = RES[f"Account_{account_id}"]
    for triple in kg.triples((account, None, None)):
        ctx.add(triple)
    for contact in set(kg.subjects(CRM.worksFor, account)) | set(kg.subjects(CRM.decisionMakerFor, deal)):
        for triple in kg.triples((contact, None, None)):
            ctx.add(triple)
    return ctx.serialize(format="turtle")


def clean(turtle_text: str) -> str:
    """Strip markdown code fences if the model adds them despite instructions."""
    lines = [ln for ln in turtle_text.splitlines() if not ln.strip().startswith("```")]
    return "\n".join(lines).strip()


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    os.makedirs("extracted", exist_ok=True)
    os.makedirs(os.path.join("extracted", "failed"), exist_ok=True)

    with open("TranscriptRDFTurtleExtractionPrompt.md", encoding="utf-8") as f:
        template = f.read()
    with open("sales_kg_ontology_v1.ttl", encoding="utf-8") as f:
        ontology = f.read()
    kg = Graph()
    kg.parse("kg.nt")  # run build.py first

    with open(os.path.join("mock_crm_dataset", "transcripts.csv"), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]

    for row in rows:
        tid = row["transcript_id"]
        prompt = template
        prompt = prompt.replace("{{ONTOLOGY\\_TTL}}", ontology)
        prompt = prompt.replace("{{CRM\\_CONTEXT}}", crm_context(kg, row["deal_id"], row["account_id"]))
        prompt = prompt.replace("{{TRANSCRIPT\\_ID}}", tid)
        prompt = prompt.replace("{{DEAL\\_ID}}", row["deal_id"])
        prompt = prompt.replace("{{ACCOUNT\\_ID}}", row["account_id"])
        prompt = prompt.replace("{{ACTIVITY\\_DATE}}", row["activity_date"])
        prompt = prompt.replace("{{CHANNEL}}", row["channel"])
        prompt = prompt.replace("{{TRANSCRIPT}}", row["transcript"])

        try:
            r = requests.post(OLLAMA_URL,
                              json={"model": MODEL, "prompt": prompt, "stream": False,
                                    "options": {"temperature": 0, "num_ctx": 32768}},
                              timeout=600)
            r.raise_for_status()
            raw = clean(r.json()["response"])
        except Exception as e:  # noqa: BLE001 - sandbox: save and continue
            with open(os.path.join("extracted", "failed", f"{tid}.txt"), "w", encoding="utf-8") as f:
                f.write(f"GENERATION ERROR: {e}\n")
            print(tid, "generation failed:", e)
            continue

        try:
            Graph().parse(data=raw, format="turtle")
        except Exception as e:  # noqa: BLE001 - sandbox: save and continue
            with open(os.path.join("extracted", "failed", f"{tid}.txt"), "w", encoding="utf-8") as f:
                f.write(raw + f"\n\nPARSE ERROR: {e}\n")
            print(tid, "parse failed, saved to extracted/failed/")
            continue

        with open(os.path.join("extracted", f"{tid}.ttl"), "w", encoding="utf-8") as f:
            f.write(raw + "\n")
        print(tid, "ok ->", os.path.join("extracted", f"{tid}.ttl"))


if __name__ == "__main__":
    main()
