"""Unit tests for the ingestion service (``app.ingestion.service``).

Covers primary-key CSV merging, single-transcript appending, and the offline
``build`` + ``index`` pipeline steps run against the tracked
``tests/fixtures/new_crm/`` fixtures. ``build`` is pointed at a tmp ``KG_NT`` and
``index`` at a tmp ``CHROMA_DIR`` so the repo-root ``kg.nt``/``chroma_db`` are
never touched.
"""
import csv
import shutil
from pathlib import Path

import pytest

from app import config
from app.ingestion import service
from app.retrieval import keyword

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "new_crm"


# --- merge_csv_files ----------------------------------------------------------
def test_merge_csv_files_creates_file_with_header(tmp_path):
    result = service.merge_csv_files(
        [("accounts.csv", b"account_id,account_name\nA201,New Co\n")], tmp_path
    )

    assert result == {"accounts.csv": 1}
    path = tmp_path / "accounts.csv"
    assert path.exists()

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == ["account_id", "account_name"]
        rows = list(reader)

    assert rows == [{"account_id": "A201", "account_name": "New Co"}]


def test_merge_csv_files_appends_new_rows(tmp_path):
    first = b"account_id,account_name\nA201,New Co\n"
    service.merge_csv_files([("accounts.csv", first)], tmp_path)

    result = service.merge_csv_files(
        [("accounts.csv", b"account_id,account_name\nA202,Other Co\n")], tmp_path
    )

    assert result == {"accounts.csv": 1}
    path = tmp_path / "accounts.csv"
    rows = _read_rows(path)
    assert [r["account_id"] for r in rows] == ["A201", "A202"]
    assert rows[0]["account_name"] == "New Co"

    # The header is written exactly once.
    header_lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("account_id,")
    ]
    assert len(header_lines) == 1


def test_merge_csv_files_conflict_raises_and_writes_nothing(tmp_path):
    service.merge_csv_files(
        [("accounts.csv", b"account_id,account_name\nA201,New Co\n")], tmp_path
    )
    path = tmp_path / "accounts.csv"
    before = path.read_bytes()

    with pytest.raises(ValueError, match=r"duplicate account_id\(s\): \['A201'\]"):
        service.merge_csv_files(
            [("accounts.csv", b"account_id,account_name\nA201,Duplicate\n")], tmp_path
        )

    assert path.read_bytes() == before


def test_merge_csv_files_duplicate_within_upload_raises(tmp_path):
    data = b"account_id,account_name\nA201,One\nA201,Two\n"

    with pytest.raises(ValueError, match=r"duplicate account_id\(s\): \['A201'\]"):
        service.merge_csv_files([("accounts.csv", data)], tmp_path)

    assert not (tmp_path / "accounts.csv").exists()


def test_merge_csv_files_unknown_table_raises(tmp_path):
    with pytest.raises(ValueError, match=r"unknown table x.csv"):
        service.merge_csv_files([("x.csv", b"a,b\n1,2\n")], tmp_path)


# --- append_transcript_rows ---------------------------------------------------
def _row(transcript_id="T101", transcript="hello", **overrides):
    row = {
        "transcript_id": transcript_id,
        "deal_id": "D101",
        "account_id": "A101",
        "contact_ids": "C001;C002",
        "activity_date": "2026-09-20",
        "channel": "Phone",
        "transcript": transcript,
    }
    row.update(overrides)
    return row


def _read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_append_transcript_rows_creates_file_with_header(tmp_path):
    appended = service.append_transcript_rows(tmp_path, [_row()])

    assert appended == ["T101"]
    path = tmp_path / "transcripts.csv"
    assert path.exists()

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == [
            "transcript_id",
            "deal_id",
            "account_id",
            "contact_ids",
            "activity_date",
            "channel",
            "transcript",
        ]
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["transcript_id"] == "T101"
    assert rows[0]["contact_ids"] == "C001;C002"
    assert rows[0]["transcript"] == "hello"


def test_append_transcript_rows_contact_ids_optional(tmp_path):
    row = _row()
    del row["contact_ids"]

    service.append_transcript_rows(tmp_path, [row])

    assert _read_rows(tmp_path / "transcripts.csv")[0]["contact_ids"] == ""


def test_append_transcript_rows_appends_without_repeating_header(tmp_path):
    service.append_transcript_rows(tmp_path, [_row(transcript="first")])
    appended = service.append_transcript_rows(
        tmp_path, [_row(transcript_id="T102", transcript="second")]
    )

    assert appended == ["T102"]
    rows = _read_rows(tmp_path / "transcripts.csv")
    assert [r["transcript_id"] for r in rows] == ["T101", "T102"]
    assert rows[1]["transcript"] == "second"

    # The header is written exactly once.
    header_lines = [
        line
        for line in (tmp_path / "transcripts.csv").read_text(encoding="utf-8").splitlines()
        if line.startswith("transcript_id,")
    ]
    assert len(header_lines) == 1


def test_append_transcript_rows_duplicate_raises(tmp_path):
    service.append_transcript_rows(tmp_path, [_row()])

    with pytest.raises(ValueError, match="duplicate transcript_id: T101"):
        service.append_transcript_rows(tmp_path, [_row(transcript="second")])

    # Duplicates within the same batch are rejected too.
    with pytest.raises(ValueError, match="duplicate transcript_id: T201"):
        service.append_transcript_rows(
            tmp_path, [_row(transcript_id="T201"), _row(transcript_id="T201")]
        )


def test_append_transcript_rows_missing_field_raises(tmp_path):
    row = _row(transcript_id="T105", channel="")

    with pytest.raises(ValueError) as excinfo:
        service.append_transcript_rows(tmp_path, [row])

    message = str(excinfo.value)
    assert "T105" in message
    assert "channel" in message
    assert not (tmp_path / "transcripts.csv").exists()


# --- run (build + index) ------------------------------------------------------
def test_run_build_index(tmp_path, monkeypatch):
    data_dir = tmp_path / "crm"
    shutil.copytree(FIXTURES_DIR, data_dir)

    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    # Keep build's kg.nt out of the repo root.
    monkeypatch.setenv("KG_NT", str(tmp_path / "kg.nt"))
    keyword.reset_cache()

    result = service.run(data_dir, steps=("build", "index"))

    keyword.reset_cache()

    assert "error" not in result
    assert (tmp_path / "chroma").exists()

    build_result = result["build"]
    assert not isinstance(build_result, dict), f"build degraded: {build_result}"
    assert build_result[0] > 0

    index_result = result["index"]
    assert not isinstance(index_result, dict), f"index degraded: {index_result}"
    assert index_result >= 1
