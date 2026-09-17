"""Queue worker (M9 part 2): claim, dispatch and finish jobs.

Synchronous, in-process worker. ``run_forever`` loops against the shared engine
until interrupted; ``process_one`` performs a single claim -> dispatch -> finish
cycle (used by the loop and by the in-process ``wait_for_job`` test helper).
Nothing connects to the database at import time.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import sessionmaker

from app import config
from app.db import engine as db_engine
from app.db.models import Job
from app.queue import core

logger = logging.getLogger(__name__)


def process_one(db, cap: int = 2) -> Job | None:
    """Claim and process a single job, committing ``done``/``failed``.

    Returns the refreshed job, or ``None`` when there is nothing to claim.
    """
    from app.ingestion import service  # local import to avoid import cycles

    job = core.claim_next(db, cap)
    if job is None:
        return None
    try:
        result = service.process_job(job)
        return core.complete(db, job.id, result)
    except Exception as exc:  # noqa: BLE001 - any failure marks the job failed
        return core.fail(db, job.id, str(exc))


def run_forever(poll_s: float = 2.0) -> None:
    """Run the worker loop until interrupted; sleep ``poll_s`` when idle.

    Survives transient failures (e.g. the DB schema not yet created at boot)
    by catching any exception, logging it and retrying after ``poll_s``.
    """
    cap = config.INGEST_CONCURRENCY
    while True:
        try:
            Session = sessionmaker(
                bind=db_engine.get_engine(), autocommit=False, autoflush=False
            )
            db = Session()
            try:
                job = process_one(db, cap=cap)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - keep polling through outages
            logger.warning("worker loop error; retrying: %s", exc)
            job = None
        if job is None:
            time.sleep(poll_s)


def wait_for_job(job_id: int, user_id: int, timeout_s: float = 120) -> dict:
    """Drive the worker in-process until ``job_id`` reaches done/failed.

    Claims and processes queued jobs (so jobs queued ahead of the target also
    run). Returns ``{"id", "status", "result", "error"}``; raises
    :class:`TimeoutError` if the job has not settled within ``timeout_s``.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        Session = sessionmaker(bind=db_engine.get_engine(), autocommit=False, autoflush=False)
        db = Session()
        try:
            job = core.get_job(db, job_id, user_id)
            if job is not None and job.status in ("done", "failed"):
                return {
                    "id": job.id,
                    "status": job.status,
                    "result": job.result,
                    "error": job.error,
                }
            processed = process_one(db, cap=config.INGEST_CONCURRENCY)
        finally:
            db.close()

        if time.monotonic() >= deadline:
            raise TimeoutError(f"job {job_id} did not finish within {timeout_s}s")
        if processed is None:
            time.sleep(0.05)


if __name__ == "__main__":
    run_forever()
