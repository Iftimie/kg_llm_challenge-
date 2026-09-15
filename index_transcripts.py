"""Index all transcripts into local ChromaDB. Run: python index_transcripts.py"""
import csv

import chromadb

client = chromadb.PersistentClient(path="chroma_db")
collection = client.get_or_create_collection("transcripts")

with open("mock_crm_dataset/transcripts.csv", newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

collection.upsert(
    ids=[r["transcript_id"] for r in rows],
    documents=[r["transcript"] for r in rows],
    metadatas=[{"deal_id": r["deal_id"], "account_id": r["account_id"],
                "activity_date": r["activity_date"], "channel": r["channel"]} for r in rows],
)
print(f"indexed {len(rows)} transcripts -> chroma_db/")
