"""Queue core tests (M9 part 1): in-memory SQLite coverage.

Uses the shared ``session`` fixture (full schema per test) so no Postgres or
live service is required.
"""
from app.db.models import User
from app.queue.core import (
    claim_next,
    complete,
    enqueue,
    fail,
    get_job,
    list_jobs,
)


def test_queued_running_done(session):
    job = enqueue(session, "ingest_csv", {"path": "x.csv"}, user_id=1)
    assert job.status == "queued"

    claimed = claim_next(session)
    assert claimed.id == job.id
    assert claimed.status == "running"

    done = complete(session, job.id, {"ok": True})
    assert done.status == "done"
    assert done.result == {"ok": True}


def test_concurrency_cap_respected(session):
    ids = [enqueue(session, "ingest_csv", {"i": i}, user_id=1).id for i in range(3)]

    first = claim_next(session, cap=2)
    second = claim_next(session, cap=2)
    assert first is not None
    assert second is not None
    assert claim_next(session, cap=2) is None

    complete(session, first.id, {"ok": True})
    third = claim_next(session, cap=2)
    assert third is not None


def test_failed_job_surfaces_error(session):
    job = enqueue(session, "ingest_transcript", {"id": "T101"}, user_id=1)
    claim_next(session)

    failed = fail(session, job.id, "boom")

    assert failed.status == "failed"
    assert failed.error == "boom"


def test_jobs_scoped_to_user(session):
    session.add_all(
        [
            User(email="u1@example.com", password_hash="h"),
            User(email="u2@example.com", password_hash="h"),
        ]
    )
    session.commit()

    j1 = enqueue(session, "ingest_csv", {"a": 1}, user_id=1)
    j2 = enqueue(session, "ingest_csv", {"a": 2}, user_id=2)

    assert get_job(session, j1.id, 1) is not None
    assert get_job(session, j1.id, 2) is None
    assert get_job(session, j2.id, 2) is not None
    assert get_job(session, j2.id, 1) is None

    assert [j.id for j in list_jobs(session, 1)] == [j1.id]
    assert [j.id for j in list_jobs(session, 2)] == [j2.id]
