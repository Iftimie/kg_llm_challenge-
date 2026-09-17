"""Direct CSV lookup helpers for individual transcripts."""
import csv

from app import config
from app.ingestion.service import TRANSCRIPT_FIELDS

_CSV_NAME = "transcripts.csv"


def _rows():
    path = config.DATA_DIR / _CSV_NAME
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_transcript(transcript_id) -> dict:
    """Return the requested transcript fields, or raise ``KeyError`` if missing."""
    for r in _rows():
        if r.get("transcript_id") == transcript_id:
            data = {field: r[field] for field in TRANSCRIPT_FIELDS}
            data["contact_ids"] = [
                part.strip() for part in data["contact_ids"].split(";") if part.strip()
            ]
            return data
    raise KeyError(f"unknown transcript {transcript_id}")


def list_transcript_ids() -> list:
    return [r["transcript_id"] for r in _rows()]
