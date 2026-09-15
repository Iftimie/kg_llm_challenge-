"""Index all transcripts into local ChromaDB. Run: python index_transcripts.py"""
import csv
import os
import pathlib

import chromadb

REPO_ROOT = pathlib.Path(__file__).parent


def index_transcripts(transcripts_csv=None, chroma_dir=None) -> int:
    """Index all transcripts into a local ChromaDB persistent client.

    Returns the number of transcripts indexed.
    """
    if transcripts_csv is None:
        data_dir = pathlib.Path(os.environ.get("DATA_DIR", str(REPO_ROOT / "mock_crm_dataset")))
        transcripts_csv = data_dir / "transcripts.csv"
    else:
        transcripts_csv = pathlib.Path(transcripts_csv)

    chroma_dir = (
        pathlib.Path(chroma_dir)
        if chroma_dir is not None
        else pathlib.Path(os.environ.get("CHROMA_DIR", str(REPO_ROOT / "chroma_db")))
    )

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_or_create_collection("transcripts")

    with open(transcripts_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    collection.upsert(
        ids=[r["transcript_id"] for r in rows],
        documents=[r["transcript"] for r in rows],
        metadatas=[{"deal_id": r["deal_id"], "account_id": r["account_id"],
                    "activity_date": r["activity_date"], "channel": r["channel"]} for r in rows],
    )
    print(f"indexed {len(rows)} transcripts -> {chroma_dir}/")

    return len(rows)


def main() -> None:
    index_transcripts()


if __name__ == "__main__":
    main()
