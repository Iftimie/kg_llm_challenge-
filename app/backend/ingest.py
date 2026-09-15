"""Ingestion endpoints: standard CRM CSVs plus transcript-row append.

``POST /api/ingest`` accepts only the CRM table ``.csv`` files (``accounts.csv``,
``deals.csv``, ``contacts.csv``, ``activities.csv``). Uploaded rows are merged
into the existing tables by primary key; a duplicate key (within the upload or
already on disk) rejects the whole upload with ``400`` and writes nothing. The
offline-safe ``build`` + ``load`` pipeline steps then run. ``transcripts.csv``
must go through ``POST /api/ingest/transcript`` instead.
``POST /api/ingest/transcript`` accepts transcript rows in the existing
7-column ``transcripts.csv`` format as a ``.csv`` file upload, appends them to
``transcripts.csv`` and reruns ``build`` -> ``index`` -> ``extract`` -> ``load``
against only the newly appended transcript ids. Any step that degrades to
``{"error": ...}`` is reported in ``errors`` while the response still returns
``200``; only unexpected exceptions become ``500``.
"""
import csv
import io
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app import config
from app.ingestion import service

router = APIRouter()


class StepResult(BaseModel):
    """Flexible holder for one ingestion step's result (accepts arbitrary keys)."""

    model_config = ConfigDict(extra="allow")


class IngestResponse(BaseModel):
    status: str
    data_dir: str
    staged_csvs: list[str]
    staged_transcripts: list[str]
    steps: dict[str, Any]
    triples: int | None = None
    transcripts_indexed: int | None = None
    errors: list[str] = Field(default_factory=list)


def _step_error(value: Any) -> str | None:
    """Return the error message when a step degraded to ``{"error": ...}``."""
    if isinstance(value, dict) and "error" in value:
        return str(value["error"])
    return None


def _collect_step_errors(result: dict) -> list[str]:
    """Build the ordered ``errors`` list for the steps that degraded to errors."""
    errors: list[str] = []

    for step, value in result.items():
        message = _step_error(value)
        if message:
            errors.append(f"{step}: {message}")

    return errors


@router.post("/api/ingest")
async def ingest(files: list[UploadFile] = File(...)) -> IngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")

    csv_files: list[tuple[str, bytes]] = []
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
        csv_files.append((filename, data))

    if unsupported:
        raise HTTPException(
            status_code=400,
            detail=(
                f"only .csv files are accepted by /api/ingest, got: {unsupported}. "
                "To add a transcript, use POST /api/ingest/transcript."
            ),
        )

    try:
        merged = service.merge_csv_files(csv_files, config.DATA_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # CSV ingestion always runs build -> load (never index/extract).
    steps: dict[str, Any] = {"merge": merged}

    try:
        steps.update(service.run(config.DATA_DIR, steps=("build", "load")))
    except Exception as exc:  # noqa: BLE001 - service.run is not expected to raise
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    triples: int | None = None
    build_value = steps.get("build")
    if not _step_error(build_value) and isinstance(build_value, (tuple, list)) and build_value:
        triples = build_value[0]

    return IngestResponse(
        status="ok",
        data_dir=str(config.DATA_DIR),
        staged_csvs=list(merged),
        staged_transcripts=[],
        steps=steps,
        triples=triples,
        transcripts_indexed=None,
        errors=_collect_step_errors(steps),
    )


@router.post("/api/ingest/transcript")
async def ingest_transcript(file: UploadFile = File(...)) -> IngestResponse:
    """Append transcript rows from a ``.csv`` upload and re-index.

    Rows use the canonical 7-column ``transcripts.csv`` layout (a header row is
    optional). ``contact_ids`` is optional per row and defaults to ``""``.
    """
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="only .csv files are accepted by /api/ingest/transcript",
        )

    data = await file.read()
    content = data.decode("utf-8", errors="replace")

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
        if len(raw) < 6:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"row {position} has {len(raw)} columns; expected at least 6 "
                    "in transcripts.csv format (transcript_id,deal_id,account_id,"
                    "contact_ids,activity_date,channel,transcript)"
                ),
            )
        if len(raw) < len(service._TRANSCRIPT_FIELDS):
            # contact_ids omitted: insert the optional empty column.
            raw = raw[:3] + [""] + raw[3:]
        rows.append(dict(zip(service._TRANSCRIPT_FIELDS, raw)))

    try:
        appended = service.append_transcript_rows(config.DATA_DIR, rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = service.run(
            config.DATA_DIR,
            steps=("build", "index", "extract", "load"),
            extract_ids=appended,
        )
    except Exception as exc:  # noqa: BLE001 - service.run is not expected to raise
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    index_value = result.get("index")
    transcripts_indexed = index_value if isinstance(index_value, int) else None

    return IngestResponse(
        status="ok",
        data_dir=str(config.DATA_DIR),
        staged_csvs=[],
        staged_transcripts=appended,
        steps=result,
        triples=None,
        transcripts_indexed=transcripts_indexed,
        errors=_collect_step_errors(result),
    )
