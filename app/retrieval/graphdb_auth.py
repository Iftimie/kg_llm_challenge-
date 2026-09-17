"""GraphDB credential helper (stdlib only).

GraphDB 10 ships with security disabled by default (open), so local dev runs
with no auth. Once security is enabled via ``scripts/graphdb_secure.py`` the
compose app env sets ``GRAPHDB_USER``/``GRAPHDB_PASSWORD`` to the read-only
``reader`` account; chat-time reads authenticate with it. Ingest writes use
admin creds via the same env vars in ``load.py``.
"""
from app import config


def auth():
    """Return ``(user, password)`` when GraphDB auth is configured, else ``None``.

    An empty ``GRAPHDB_USER`` means "security is off", so no credentials are
    sent and GraphDB is reached anonymously. When set, the tuple is passed
    straight to ``requests`` as the ``auth`` kwarg (HTTP Basic).
    """
    if config.GRAPHDB_USER:
        return (config.GRAPHDB_USER, config.GRAPHDB_PASSWORD)
    return None
