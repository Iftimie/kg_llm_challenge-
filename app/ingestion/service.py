"""Ingestion orchestrator for the Sales Intelligence KG.

Wraps the ``app.ingestion`` pipeline modules (build/load/index_transcripts/
extract) into a single entry point that never raises: each step is run
independently and degrades into ``{"error": ...}`` on failure.
"""
import csv
import importlib
import io
import logging
import shutil
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)


def _import_pipeline(mod: str):
    """Lazily import a pipeline module under ``app.ingestion``."""
    return importlib.import_module(f"app.ingestion.{mod}")


def run(
    data_dir=None,
    steps=("build", "load", "index"),
    extract_limit=None,
    extract_ids=None,
) -> dict:
    """Run the ingestion pipeline, one step at a time.

    ``extract_ids``, when given, restricts the ``extract`` step to those
    ``transcript_id`` values. Returns a dict keyed by step name. Each value
    summarizes that step and, on failure, is replaced by ``{"error": <message>}``.
    Never raises (except KeyboardInterrupt).
    """
    if data_dir is None:
        data_dir = config.DATA_DIR
    data_dir = Path(data_dir)

    summary: dict = {}
    for step in steps:
        summary[step] = _run_step(step, data_dir, extract_limit, extract_ids)
    return summary


def _run_step(step: str, data_dir: Path, extract_limit, extract_ids=None):
    try:
        if step == "build":
            build_mod = _import_pipeline("build")
            ensure_transcripts_csv(data_dir)
            triples, _ = build_mod.build(data_dir)
            logger.info("build: %s triples", triples)
            return (triples, True)

        if step == "load":
            load_mod = _import_pipeline("load")
            result = load_mod.load(extracted_dir=data_dir / "extracted")
            repo = result["repo"]
            total = result["total_triples"]
            logger.info("load: repo=%s total_triples=%s", repo, total)
            return (repo, total)

        if step == "index":
            index_mod = _import_pipeline("index_transcripts")
            count = index_mod.index_transcripts(
                transcripts_csv=data_dir / "transcripts.csv",
                chroma_dir=config.CHROMA_DIR,
            )
            from app.retrieval import keyword

            keyword.reset_cache()
            logger.info("index: %s transcripts", count)
            return count

        if step == "extract":
            extract_mod = _import_pipeline("extract")
            result = extract_mod.extract(data_dir, limit=extract_limit, ids=extract_ids)
            ok = list(result.get("ok", []))
            failed = list(result.get("failed", []))
            logger.info("extract: ok=%s failed=%s", len(ok), len(failed))
            return {"ok": ok, "failed": failed}

        if step == "clear":
            load_mod = _import_pipeline("load")
            result = load_mod.clear()
            logger.info("clear: %s graphs", result.get("cleared"))
            return result

        raise ValueError(f"unknown step: {step!r}")
    except BaseException as exc:  # noqa: BLE001 - degrade per-step, never raise
        if isinstance(exc, KeyboardInterrupt):
            raise
        logger.error("step %r failed: %s", step, exc)
        return {"error": str(exc)}


_TABLE_KEYS = {
    "accounts.csv": "account_id",
    "deals.csv": "deal_id",
    "contacts.csv": "contact_id",
    "activities.csv": "activity_id",
    "transcripts.csv": "transcript_id",
}


def merge_csv_files(files, target_dir) -> dict:
    """Merge CRM table CSV uploads into ``target_dir`` by primary key.

    ``files`` is an iterable of ``(filename, bytes)``. Rows are appended to the
    existing table: a row is rejected when its primary key is duplicated within
    the upload or already present on disk. Every file is validated in full
    before anything is written, so a rejected upload leaves the target files
    byte-for-byte untouched (atomic across the whole upload).

    Returns ``{filename: added_count}`` for the merged tables.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    entries: dict = {}

    for filename, data in list(files):
        name = Path(str(filename)).name.lower()
        if name not in _TABLE_KEYS:
            raise ValueError(
                f"unknown table {filename}; expected one of {sorted(_TABLE_KEYS)}"
            )
        key = _TABLE_KEYS[name]

        if isinstance(data, (bytes, bytearray)):
            text = data.decode("utf-8-sig", errors="replace")
        else:
            text = str(data)
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError(f"{filename}: empty or headerless CSV")
        upload_header = list(reader.fieldnames)
        rows = list(reader)

        path = target_dir / name
        if name not in entries:
            existing_header: list = []
            existing_keys: set = set()
            if path.exists():
                with open(path, newline="", encoding="utf-8-sig") as fh:
                    existing_reader = csv.DictReader(fh)
                    existing_header = list(existing_reader.fieldnames or [])
                    existing_keys = {
                        (row.get(key) or "").strip() for row in existing_reader
                    }
            entries[name] = {
                "path": path,
                "header": existing_header,
                "upload_header": upload_header,
                "keys": existing_keys,
                "rows": [],
            }

        entry = entries[name]

        if entry["header"]:
            missing = [col for col in entry["header"] if col not in upload_header]
            if missing:
                raise ValueError(f"{filename}: missing column(s) {missing}")

        for row in rows:
            if not (row.get(key) or "").strip():
                raise ValueError(f"{filename}: row missing {key}")

        seen: set = set()
        conflicts: set = set()
        for row in rows:
            value = (row.get(key) or "").strip()
            if value in seen:
                conflicts.add(value)
            seen.add(value)
        conflicts |= seen & entry["keys"]
        if conflicts:
            raise ValueError(
                f"{filename}: duplicate {key}(s): {sorted(conflicts)}"
            )

        entry["keys"].update(seen)
        entry["rows"].extend(rows)

    summary: dict = {}
    for name, entry in entries.items():
        summary[name] = len(entry["rows"])
        if not entry["rows"]:
            continue
        header = entry["header"] or entry["upload_header"]
        with open(entry["path"], "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=header)
            if not entry["header"]:
                writer.writeheader()
            for row in entry["rows"]:
                writer.writerow(
                    {
                        col: ("" if row.get(col) is None else row.get(col))
                        for col in header
                    }
                )
    return summary


_TRANSCRIPT_HEADER = (
    "transcript_id,deal_id,account_id,contact_ids,activity_date,channel,transcript"
)


def ensure_transcripts_csv(target_dir) -> Path:
    """Create ``target_dir/transcripts.csv`` with just the header if missing.

    ``mappings.ttl`` references ``transcripts.csv``, so ``build`` fails unless
    the file exists even when there are no transcript rows to load. Returns the
    path either way; an existing file is left untouched.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "transcripts.csv"
    if not path.exists():
        path.write_text(_TRANSCRIPT_HEADER + "\n", encoding="utf-8")
    return path


TRANSCRIPT_FIELDS = (
    "transcript_id",
    "deal_id",
    "account_id",
    "contact_ids",
    "activity_date",
    "channel",
    "transcript",
)

_TRANSCRIPT_FIELDS = list(TRANSCRIPT_FIELDS)


def append_transcript_rows(target_dir, rows) -> list:
    """Append transcript rows (dicts) to ``target_dir/transcripts.csv``.

    ``rows`` is a list of dicts whose keys come from ``_TRANSCRIPT_FIELDS``;
    ``contact_ids`` is required and must be non-empty. Every row must have a
    non-empty ``transcript_id``, ``deal_id``, ``account_id``, ``contact_ids``,
    ``activity_date``, ``channel`` and ``transcript``. Duplicate ``transcript_id``
    values are rejected both within the batch and against the existing file.

    Creates the directory/file with the standard 7-column header when the file
    is new or empty, and appends otherwise. Returns the appended transcript ids.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    path = target_dir / "transcripts.csv"
    required = [
        "transcript_id",
        "deal_id",
        "account_id",
        "contact_ids",
        "activity_date",
        "channel",
        "transcript",
    ]

    normalized = []
    seen: set = set()
    for row in rows:
        tid = str(row.get("transcript_id", "") or "").strip()
        for field in required:
            if not str(row.get(field, "") or "").strip():
                raise ValueError(
                    f"transcript {tid or '(missing transcript_id)'!r} "
                    f"missing required field: {field}"
                )
        if tid in seen:
            raise ValueError(f"duplicate transcript_id: {tid}")
        seen.add(tid)
        normalized.append(
            {field: str(row.get(field, "") or "") for field in _TRANSCRIPT_FIELDS}
        )

    has_content = path.exists() and path.stat().st_size > 0
    existing_ids: set = set()
    if has_content:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames:
                existing_ids = {r.get("transcript_id") for r in reader}

    for item in normalized:
        if item["transcript_id"] in existing_ids:
            raise ValueError(
                f"duplicate transcript_id: {item['transcript_id']}"
            )

    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_TRANSCRIPT_FIELDS)
        if not has_content:
            writer.writeheader()
        writer.writerows(normalized)

    return [item["transcript_id"] for item in normalized]


def process_job(job, db=None) -> dict:
    """Dispatch a queued ingestion job to its worker action and return a summary.

    ``job`` is an ORM ``Job`` (or any object exposing ``.kind`` and ``.payload``).
    ``db`` is accepted for symmetry with the worker but is unused: this function
    only performs the work and returns a result dict; the worker is responsible
    for committing ``done``/``failed`` on the job. Raises ``ValueError`` for an
    unknown ``kind``.

    ``ingest_csv`` payloads carry ``{"files": {filename: text}}`` (file bytes
    stored as UTF-8 text so the payload is JSON-safe); they are decoded back to
    ``(filename, bytes)``, merged, then ``build`` + ``load`` run. ``ingest_transcript``
    payloads carry ``{"rows": [rowdict, ...]}``; rows are appended and ``build`` ->
    ``index`` -> ``extract`` -> ``load`` run against only the appended ids.
    ``clear_kg`` carries no payload; it deletes the on-disk CSVs + extracted
    facts and clears the GraphDB graphs (to re-ingest the same files from scratch).
    """
    from app import config  # local import to avoid import cycles

    kind = job.kind
    payload = job.payload or {}

    if kind == "ingest_csv":
        files_raw = payload.get("files") or {}
        files = [(filename, text.encode("utf-8")) for filename, text in files_raw.items()]
        merged = merge_csv_files(files, config.DATA_DIR)
        result = run(config.DATA_DIR, steps=("build", "load"))
        return {"merge": merged, **result}

    if kind == "ingest_transcript":
        rows = payload.get("rows") or []
        appended = append_transcript_rows(config.DATA_DIR, rows)
        result = run(
            config.DATA_DIR,
            steps=("build", "index", "extract", "load"),
            extract_ids=appended,
        )
        return {"appended": appended, **result}

    if kind == "clear_kg":
        # Wipe the source CSVs + derived transcript facts, then clear the graph.
        for name in ("accounts.csv", "deals.csv", "contacts.csv", "activities.csv", "transcripts.csv"):
            (config.DATA_DIR / name).unlink(missing_ok=True)
        shutil.rmtree(config.DATA_DIR / "extracted", ignore_errors=True)
        return run(config.DATA_DIR, steps=("clear",))

    raise ValueError(f"unknown job kind: {kind!r}")
