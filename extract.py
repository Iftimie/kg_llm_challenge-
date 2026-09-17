"""Extract KG triples from transcripts with the configured DeepSeek model.

Uses the same DeepSeek model as the agents (``config.EXTRACT_MODEL``, which
defaults to ``config.DEEPSEEK_MODEL``). Run: python extract.py [limit]
"""
import csv
import os
import pathlib
import sys

import requests
from rdflib import Graph, Namespace, URIRef

from app import config

REPO_ROOT = pathlib.Path(__file__).parent

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


def _generate(prompt: str) -> str:
    """Send one extraction prompt to the configured DeepSeek model."""
    key = config.DEEPSEEK_APIKEY
    if not key:
        raise RuntimeError("DEEPSEEK_APIKEY is not set")

    url = config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": config.EXTRACT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=600,
    )
    try:
        r.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(f"DeepSeek error {r.status_code}: {r.text[:1000]}") from exc
    return r.json()["choices"][0]["message"]["content"]


def extract(data_dir=None, limit=None, ids=None) -> dict:
    """Extract KG triples from transcripts with the configured DeepSeek model.

    Uses the same model as the agents. ``ids``, when a non-empty list, restricts
    processing to those ``transcript_id`` values while preserving the CSV row
    order; ``limit`` is applied after that filtering. Returns
    ``{ok: [ids], failed: [ids]}``.
    """
    if data_dir is None:
        data_dir = pathlib.Path(os.environ.get("DATA_DIR", str(REPO_ROOT / "mock_crm_dataset")))
    else:
        data_dir = pathlib.Path(data_dir)

    extracted_dir = data_dir / "extracted"
    os.makedirs(extracted_dir, exist_ok=True)
    os.makedirs(extracted_dir / "failed", exist_ok=True)

    with open(REPO_ROOT / "TranscriptRDFTurtleExtractionPrompt.md", encoding="utf-8") as f:
        template = f.read()
    with open(REPO_ROOT / "sales_kg_ontology_v1.ttl", encoding="utf-8") as f:
        ontology = f.read()
    kg = Graph()
    kg.parse(str(REPO_ROOT / "kg.nt"))  # run build.py first

    with open(data_dir / "transcripts.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if ids:
        wanted = set(ids)
        rows = [row for row in rows if row["transcript_id"] in wanted]
    if limit:
        rows = rows[:limit]

    ok = []
    failed = []

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
            raw = clean(_generate(prompt))
        except Exception as e:  # noqa: BLE001 - sandbox: save and continue
            with open(extracted_dir / "failed" / f"{tid}.txt", "w", encoding="utf-8") as f:
                f.write(f"GENERATION ERROR: {e}\n")
            print(tid, "generation failed:", e)
            failed.append(tid)
            continue

        try:
            Graph().parse(data=raw, format="turtle")
        except Exception as e:  # noqa: BLE001 - sandbox: save and continue
            with open(extracted_dir / "failed" / f"{tid}.txt", "w", encoding="utf-8") as f:
                f.write(raw + f"\n\nPARSE ERROR: {e}\n")
            print(tid, "parse failed, saved to extracted/failed/")
            failed.append(tid)
            continue

        with open(extracted_dir / f"{tid}.ttl", "w", encoding="utf-8") as f:
            f.write(raw + "\n")
        print(tid, "ok ->", extracted_dir / f"{tid}.ttl")
        ok.append(tid)

    return {"ok": ok, "failed": failed}


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    extract(limit=limit)


if __name__ == "__main__":
    main()
