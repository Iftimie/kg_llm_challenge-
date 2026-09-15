"""FastAPI ingestion endpoint tests using Starlette's TestClient (in-process).

Uses the tracked ``tests/fixtures/new_crm/`` files. ``config.DATA_DIR``,
``config.CHROMA_DIR`` and ``KG_NT`` are monkeypatched per test so staging +
build + index never touch the repo-root ``kg.nt`` or ``chroma_db``. Transcript
tests also stub the LLM (``extract._generate``) and the GraphDB loader so no
network/LLM/GraphDB call is made.
"""
import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import extract
import load as load_mod
from app import config
from app.backend.app import app
from app.retrieval import keyword

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "new_crm"

EXTRACTED_TURTLE = (
    "@prefix crm: <https://example.org/sales-kg/> .\n"
    "<https://example.org/sales-kg/resource/Blocker_T910> a crm:Blocker .\n"
)

client = TestClient(app)


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


@pytest.fixture(autouse=True)
def _reset_keyword_cache():
    keyword.reset_cache()
    yield
    keyword.reset_cache()


@pytest.fixture
def transcript_env(tmp_path, monkeypatch):
    """Isolated transcript endpoint env: no LLM/GraphDB, no repo-root writes."""
    data_dir = tmp_path / "crm"
    data_dir.mkdir()
    for name in ("accounts.csv", "contacts.csv", "deals.csv", "activities.csv"):
        (data_dir / name).write_bytes(_fixture_bytes(name))

    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setenv("KG_NT", str(tmp_path / "kg.nt"))
    monkeypatch.setattr(extract, "REPO_ROOT", tmp_path)

    # extract() reads the prompt template, ontology and kg.nt from REPO_ROOT.
    (tmp_path / "TranscriptRDFTurtleExtractionPrompt.md").write_text(
        "id {{TRANSCRIPT\\_ID}} body {{TRANSCRIPT}}\n", encoding="utf-8"
    )
    (tmp_path / "sales_kg_ontology_v1.ttl").write_text(
        "@prefix crm: <https://example.org/sales-kg/> .\n", encoding="utf-8"
    )
    (tmp_path / "kg.nt").write_text(
        "<https://example.org/sales-kg/resource/Deal_D910> "
        "<https://example.org/sales-kg/name> \"D910\" .\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(extract, "_generate", lambda prompt: EXTRACTED_TURTLE)
    # The load step must not reach GraphDB.
    monkeypatch.setattr(
        load_mod,
        "load",
        lambda *args, **kwargs: {"repo": "test", "total_triples": 0, "loaded": []},
    )
    return data_dir


def _crm_files() -> list:
    return [
        ("files", ("accounts.csv", _fixture_bytes("accounts.csv"), "text/csv")),
        ("files", ("contacts.csv", _fixture_bytes("contacts.csv"), "text/csv")),
        ("files", ("deals.csv", _fixture_bytes("deals.csv"), "text/csv")),
        ("files", ("activities.csv", _fixture_bytes("activities.csv"), "text/csv")),
    ]


def _read_transcripts(data_dir: Path) -> list:
    with open(data_dir / "transcripts.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_ingest_success(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("KG_NT", str(tmp_path / "kg.nt"))
    # No GraphDB in tests: the load step is stubbed.
    monkeypatch.setattr(
        load_mod,
        "load",
        lambda *args, **kwargs: {"repo": "test", "total_triples": 0, "loaded": []},
    )

    response = client.post("/api/ingest", files=_crm_files())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Merge is reported per table; every uploaded row is new in the empty DATA_DIR.
    assert body["steps"]["merge"] == {
        "accounts.csv": 1,
        "contacts.csv": 2,
        "deals.csv": 1,
        "activities.csv": 1,
    }
    assert set(body["staged_csvs"]) == {
        "accounts.csv",
        "contacts.csv",
        "deals.csv",
        "activities.csv",
    }
    assert body["staged_transcripts"] == []
    # merge + build + load run; index/extract belong to other endpoints.
    assert set(body["steps"]) == {"merge", "build", "load"}
    assert "index" not in body["steps"]
    assert "extract" not in body["steps"]

    build_value = body["steps"]["build"]
    assert isinstance(build_value, list) and build_value
    assert build_value[0] > 0
    assert body["triples"] > 0

    # The stubbed load step still reports under its key.
    assert "load" in body["steps"]
    assert body["transcripts_indexed"] is None


def test_ingest_csv_conflict_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("KG_NT", str(tmp_path / "kg.nt"))
    monkeypatch.setattr(
        load_mod,
        "load",
        lambda *args, **kwargs: {"repo": "test", "total_triples": 0, "loaded": []},
    )

    first = client.post("/api/ingest", files=_crm_files())
    assert first.status_code == 200

    path = tmp_path / "accounts.csv"
    before = path.read_bytes()

    second = client.post("/api/ingest", files=_crm_files())

    assert second.status_code == 400
    assert "duplicate account_id" in second.json()["detail"]
    # The rejected upload wrote nothing: the data dir file is unchanged.
    assert path.read_bytes() == before


def test_ingest_rejects_transcripts_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    response = client.post(
        "/api/ingest",
        files=[
            (
                "files",
                (
                    "transcripts.csv",
                    _fixture_bytes("transcripts.csv"),
                    "text/csv",
                ),
            )
        ],
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "/api/ingest/transcript" in detail
    assert "transcripts.csv" in detail


def test_ingest_rejects_bad_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    response = client.post(
        "/api/ingest",
        files=[("files", ("evil.exe", b"MZ\x90\x00", "application/octet-stream"))],
    )

    assert response.status_code == 400


def test_ingest_rejects_txt(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    response = client.post(
        "/api/ingest",
        files=[("files", ("T101.txt", _fixture_bytes("T101.txt"), "text/plain"))],
    )

    assert response.status_code == 400
    assert "/api/ingest/transcript" in response.json()["detail"]


def test_ingest_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    response = client.post("/api/ingest")

    assert response.status_code != 200


TRANSCRIPT_HEADER = (
    "transcript_id,deal_id,account_id,contact_ids,activity_date,channel,transcript"
)


def _csv_text(*rows: str) -> str:
    return "\n".join((TRANSCRIPT_HEADER, *rows)) + "\n"


def test_ingest_transcript_file_success(transcript_env, tmp_path):
    # 6-column row: contact_ids omitted, so it defaults to "".
    content = _csv_text("T910,D910,A910,2026-09-23,Phone,uploaded body")
    files = {"file": ("transcripts.csv", content.encode("utf-8"), "text/csv")}

    response = client.post("/api/ingest/transcript", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["staged_transcripts"] == ["T910"]
    assert body["errors"] == []
    assert (tmp_path / "chroma").exists()

    # The full offline pipeline runs for the newly appended transcript only.
    assert set(body["steps"]) == {"build", "index", "extract", "load"}
    assert isinstance(body["steps"]["index"], int)
    assert body["steps"]["index"] >= 1
    assert body["transcripts_indexed"] >= 1
    assert body["steps"]["extract"] == {"ok": ["T910"], "failed": []}

    rows = _read_transcripts(transcript_env)
    assert len(rows) == 1
    assert rows[0]["transcript_id"] == "T910"
    assert rows[0]["contact_ids"] == ""
    assert rows[0]["activity_date"] == "2026-09-23"
    assert rows[0]["channel"] == "Phone"
    assert rows[0]["transcript"] == "uploaded body"


def test_ingest_transcript_duplicate(transcript_env, tmp_path):
    content = _csv_text("T900,D900,A900,,2026-09-22,Email,first body")
    files = {"file": ("transcripts.csv", content.encode("utf-8"), "text/csv")}

    first = client.post("/api/ingest/transcript", files=files)
    assert first.status_code == 200
    assert (tmp_path / "chroma").exists()

    second = client.post("/api/ingest/transcript", files=files)

    assert second.status_code == 400
    assert "duplicate transcript_id" in second.json()["detail"]


def test_ingest_transcript_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    files = {"file": ("transcripts.csv", b"   \n  ", "text/csv")}
    response = client.post("/api/ingest/transcript", files=files)

    assert response.status_code == 400
    assert "upload a transcripts .csv file" in response.json()["detail"]


def test_ingest_transcript_too_few_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    files = {"file": ("transcripts.csv", b"T900,D900,A900\n", "text/csv")}
    response = client.post("/api/ingest/transcript", files=files)

    assert response.status_code == 400
    assert "at least 6" in response.json()["detail"]


def test_ingest_transcript_non_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    content = _csv_text("T920,D920,A920,,2026-09-24,Email,body")
    files = {"file": ("transcripts.txt", content.encode("utf-8"), "text/plain")}

    response = client.post("/api/ingest/transcript", files=files)

    assert response.status_code == 400
