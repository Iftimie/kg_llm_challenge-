"""Tests for the ``scripts.backfill_contact_ids`` backfill utility."""
import csv

from scripts import backfill_contact_ids

HEADER = [
    "transcript_id",
    "deal_id",
    "account_id",
    "contact_ids",
    "activity_date",
    "channel",
    "transcript",
]


def _write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_backfill_invents_c000_idempotent(tmp_path):
    path = tmp_path / "transcripts.csv"
    _write(
        path,
        [
            ["T001", "D001", "A001", "C001;C002", "2026-09-10", "Phone", "hello"],
            ["T002", "D002", "A002", "", "2026-09-11", "Email", "world"],
        ],
    )

    first = backfill_contact_ids.backfill(path)
    assert first["changed"] is True
    assert first["filled"] == 1
    assert _read(path)[1]["contact_ids"] == "C000"

    # Second run is a no-op: nothing to fill, nothing written.
    before = path.read_bytes()
    second = backfill_contact_ids.backfill(path)
    assert second["changed"] is False
    assert second["filled"] == 0
    assert path.read_bytes() == before
