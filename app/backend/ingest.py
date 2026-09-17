"""Ingestion endpoints: enqueue CRM CSV and transcript-row jobs (M9 part 3).

``POST /api/ingest`` accepts only the CRM table ``.csv`` files (``accounts.csv``,
``deals.csv``, ``contacts.csv``, ``activities.csv``). Uploads are validated
synchronously (unnamed files, non-``.csv`` files and ``transcripts.csv`` are
rejected with ``400``), then enqueued as an ``ingest_csv`` job and answered with
``202`` + ``{"job_id", "status"}``. ``transcripts.csv`` must go through
``POST /api/ingest/transcript`` instead.

``POST /api/ingest/transcript`` accepts transcript rows in the existing 7-column
``transcripts.csv`` format as a ``.csv`` file upload, validates the row shape and
``contact_ids`` synchronously, then enqueues an ``ingest_transcript`` job and
answers with ``202`` + ``{"job_id", "status"}``. The actual pipeline
(merge/build/index/extract/load) runs in the queue worker.
"""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.ingestion import service
from app.queue.core import enqueue

router = APIRouter()


class JobAccepted(BaseModel):
    """Synchronous acceptance response for an enqueued ingestion job."""

    job_id: int
    status: str


@router.post("/api/ingest", status_code=202)
async def ingest(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobAccepted:
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")

    payload_files: dict[str, str] = {}
    unsupported: list[str] = []

    for upload in files:
        filename = (upload.filename or "").strip()
        if not filename:
            unsupported.append("(unnamed file)")
            continue
        data = await upload.read()
        if not filename.lower().endswith(".csv"):
            unsupported.append(filename)
            continue
        if Path(filename).name.lower() == "transcripts.csv":
            raise HTTPException(
                status_code=400,
                detail=(
                    "transcripts.csv is ingested via POST /api/ingest/transcript "
                    "(the transcript form)"
                ),
            )
        payload_files[filename] = data.decode("utf-8-sig", errors="replace")

    if unsupported:
        raise HTTPException(
            status_code=400,
            detail=(
                f"only .csv files are accepted by /api/ingest, got: {unsupported}. "
                "To add a transcript, use POST /api/ingest/transcript."
            ),
        )

    job = enqueue(db, "ingest_csv", {"files": payload_files}, current_user.id)
    return JobAccepted(job_id=job.id, status=job.status)


@router.post("/api/ingest/transcript", status_code=202)
async def ingest_transcript(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobAccepted:
    """Parse a ``.csv`` transcript upload and enqueue ``ingest_transcript``.

    Rows use the canonical 7-column ``transcripts.csv`` layout (a header row is
    optional). ``contact_ids`` is required per row and must be non-empty.
    """
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="only .csv files are accepted by /api/ingest/transcript",
        )

    data = await file.read()
    content = data.decode("utf-8-sig", errors="replace")

    if not content.strip():
        raise HTTPException(status_code=400, detail="upload a transcripts .csv file")

    parsed = [
        row
        for row in csv.reader(io.StringIO(content))
        if any(cell.strip() for cell in row)
    ]

    expected_header = ",".join(service._TRANSCRIPT_FIELDS)
    if parsed and (
        ",".join(cell.strip() for cell in parsed[0]).lower()
        == expected_header.lower()
    ):
        parsed = parsed[1:]

    rows: list[dict] = []
    for position, raw in enumerate(parsed, start=1):
        if len(raw) < 7:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"row {position} has {len(raw)} columns; expected 7 "
                    "in transcripts.csv format (transcript_id,deal_id,account_id,"
                    "contact_ids,activity_date,channel,transcript)"
                ),
            )
        row = dict(zip(service._TRANSCRIPT_FIELDS, raw))
        if not str(row.get("contact_ids", "") or "").strip():
            raise HTTPException(
                status_code=400,
                detail=f"row {position} missing contact_ids",
            )
        rows.append(row)

    job = enqueue(db, "ingest_transcript", {"rows": rows}, current_user.id)
    return JobAccepted(job_id=job.id, status=job.status)


@router.post("/api/ingest/clear", status_code=202)
async def clear_kg(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobAccepted:
    """Clear the knowledge graph and the on-disk data (no upload).

    Deletes the CSV source tables + extracted facts and empties the GraphDB
    graphs, so the same files can be re-ingested from scratch.
    """
    job = enqueue(db, "clear_kg", {}, current_user.id)
    return JobAccepted(job_id=job.id, status=job.status)
