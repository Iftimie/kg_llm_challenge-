"""Best-effort GraphDB user auto-provisioning on app registration.

Standard library + ``requests`` only. Creates (or updates) a GraphDB user named
after the app user's email, granting read-only access to the configured
repository. The register endpoint calls this best-effort and swallows any
exception, so a GraphDB outage never blocks registration.
"""
from __future__ import annotations

import requests

from app import config


def provision_user(username: str, password_plaintext: str) -> None:
    """Create/update a GraphDB user with READ access to ``config.GRAPHDB_REPO``.

    POST creates the user; a 400 means it already exists (idempotent). PUT then
    replaces the user with the same password plus the granted authorities, so an
    existing user also gets its password refreshed and authority reapplied.
    """
    base = config.GRAPHDB_URL.rstrip("/")
    repo = config.GRAPHDB_REPO
    auth = (config.GRAPHDB_ADMIN_USER, config.GRAPHDB_ADMIN_PASSWORD)
    path = f"/rest/security/users/{username}"

    resp = requests.post(
        f"{base}{path}",
        auth=auth,
        json={"username": username, "password": password_plaintext},
        timeout=5,
    )
    if resp.status_code != 400:
        resp.raise_for_status()

    resp = requests.put(
        f"{base}{path}",
        auth=auth,
        json={
            "username": username,
            "password": password_plaintext,
            "grantedAuthorities": [f"READ_REPO_{repo}"],
        },
        timeout=5,
    )
    resp.raise_for_status()
