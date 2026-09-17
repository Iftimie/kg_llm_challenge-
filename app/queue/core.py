"""Queue core (M9 part 1): job enqueue, claim, completion and listing.

Synchronous, SQLAlchemy Session-based helpers backing a simple DB-backed job
queue. The worker reads ``INGEST_CONCURRENCY`` from the environment and passes
it to :func:`claim_next` as ``cap``; nothing here touches the environment.
"""
from __future__ import annotations

from sqlalchemy import func, or_, select

from app.db.models import Job

KINDS = ("ingest_csv", "ingest_transcript", "clear_kg")
STATUSES = ("queued", "running", "done", "failed")


def enqueue(db, kind: str, payload: dict, user_id: int | None) -> Job:
    """Create and persist a new ``queued`` job."""
    if kind not in KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")
    job = Job(kind=kind, status="queued", payload=payload, user_id=user_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _running_count(db) -> int:
    """Count jobs currently in the ``running`` state."""
    return db.scalar(
        select(func.count()).select_from(Job).where(Job.status == "running")
    ) or 0


def claim_next(db, cap: int = 2) -> Job | None:
    """Claim the oldest queued job if under ``cap`` running jobs, else ``None``.

    On Postgres the claim uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers
    pick distinct rows; SQLite (tests) has no such clause, so it is omitted.
    """
    if _running_count(db) >= cap:
        return None

    query = select(Job).where(Job.status == "queued").order_by(Job.id).limit(1)
    if db.get_bind().dialect.name != "sqlite":
        query = query.with_for_update(skip_locked=True)

    job = db.scalars(query).first()
    if job is None:
        return None

    job.status = "running"
    db.commit()
    db.refresh(job)
    return job


def complete(db, job_id: int, result: dict) -> Job:
    """Mark a job ``done`` and attach its result."""
    job = db.get(Job, job_id)
    job.status = "done"
    job.result = result
    db.commit()
    db.refresh(job)
    return job


def fail(db, job_id: int, error: str) -> Job:
    """Mark a job ``failed`` and attach its error message."""
    job = db.get(Job, job_id)
    job.status = "failed"
    job.error = error
    db.commit()
    db.refresh(job)
    return job


def get_job(db, job_id: int, user_id: int) -> Job | None:
    """Return the job only when it belongs to ``user_id`` (or is unowned)."""
    job = db.get(Job, job_id)
    if job is None:
        return None
    if job.user_id is None or job.user_id == user_id:
        return job
    return None


def list_jobs(db, user_id: int) -> list[Job]:
    """List the caller's jobs (plus legacy unowned rows), newest first."""
    stmt = (
        select(Job)
        .where(or_(Job.user_id == user_id, Job.user_id.is_(None)))
        .order_by(Job.id.desc())
        .limit(50)
    )
    return list(db.scalars(stmt).all())
