"""Session factory and FastAPI dependency."""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.db import engine as db_engine

# Module-level name kept for backwards compatibility. It has no bound engine:
# ``get_db()`` binds a fresh sessionmaker to the current engine on every call so
# tests that monkeypatch ``app.db.engine.get_engine`` are honoured at request
# time rather than import time.
SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def get_db():
    """FastAPI dependency that yields a session bound to the current engine."""
    Session = sessionmaker(bind=db_engine.get_engine(), autocommit=False, autoflush=False)
    db = Session()
    try:
        yield db
    finally:
        db.close()
