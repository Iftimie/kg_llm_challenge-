"""Lazily-created, cached SQLAlchemy engine.

Nothing connects at import time: the engine is built on first call to
:func:`get_engine` so the app boots (and unit tests run) without a live
database.
"""
from __future__ import annotations

import threading

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app import config

_engine: Engine | None = None
_lock = threading.Lock()


def get_engine() -> Engine:
    """Return the shared engine, building it on first use."""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = _build_engine()
    return _engine


def _build_engine() -> Engine:
    kwargs: dict = {}
    if config.DATABASE_URL.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in config.DATABASE_URL:
            # In-memory SQLite (unit tests) needs a single shared connection.
            kwargs["poolclass"] = StaticPool
        # File-backed SQLite (the browser suite's test-e2e.db) keeps the
        # default connection pool so concurrent requests each get their own
        # connection instead of interleaving on one shared StaticPool connection.
    else:
        # Fail fast when Postgres is unreachable (offline tests, no live DB)
        # instead of hanging on the OS-level TCP timeout.
        kwargs["connect_args"] = {"connect_timeout": 2}
    return create_engine(config.DATABASE_URL, **kwargs)
