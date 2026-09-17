"""Enable GraphDB 10 security and create the read-only ``reader`` account.

One-time setup, run from INSIDE the compose network::

    docker compose exec app python scripts/graphdb_secure.py

GraphDB 10 ships with security disabled (open). This script:

1. Reads ``GRAPHDB_URL`` / ``GRAPHDB_REPO`` (defaults ``http://graphdb:7200``
   / ``sales-kg``) and ``GRAPHDB_ADMIN_PASSWORD`` / ``GRAPHDB_READER_PASSWORD``
   (dummy demo defaults: admin/admin, reader/reader — interview challenge, not
   production). Setting a var to an empty string forces the missing-cred error.
2. Enables security by setting the ``admin`` password (security is still off at
   this point, so that call is unauthenticated) then POSTing ``true`` to
   ``/rest/security`` as ``admin``.
3. Creates a read-only ``reader`` user (``READ_REPO_<repo>``) for chat-time
    reads via POST (create) then PUT (grant authorities — POST on an existing
    user returns 400). Ingest writes keep using the admin password.

Idempotent: if security is already enabled it exits 0 without changing any
password. Standard library + ``requests`` only.
"""
import os
import sys

import requests

GRAPHDB_URL = os.environ.get("GRAPHDB_URL", "http://graphdb:7200").rstrip("/")
GRAPHDB_REPO = os.environ.get("GRAPHDB_REPO", "sales-kg")

ADMIN_PASSWORD = os.environ.get("GRAPHDB_ADMIN_PASSWORD", "admin")
READER_PASSWORD = os.environ.get("GRAPHDB_READER_PASSWORD", "reader")


def _call(method, path, *, auth=None, json=None):
    """Run one REST call, printing status, and raising on HTTP error."""
    url = f"{GRAPHDB_URL}{path}"
    print(f"{method} {url}")
    resp = requests.request(method, url, auth=auth, json=json, timeout=30)
    print(f"  -> {resp.status_code}")
    resp.raise_for_status()
    return resp


def main() -> int:
    if not ADMIN_PASSWORD:
        print("ERROR: GRAPHDB_ADMIN_PASSWORD is required", file=sys.stderr)
        return 2
    if not READER_PASSWORD:
        print("ERROR: GRAPHDB_READER_PASSWORD is required", file=sys.stderr)
        return 2

    try:
        # (a) Idempotence guard: never touch passwords if security is already on.
        security = _call("GET", "/rest/security").json()
        if security is True:
            print("security already enabled")
            return 0

        # (b) Set the admin password while security is still off (unauthenticated).
        _call("PATCH", "/rest/security/users/admin",
              json={"password": ADMIN_PASSWORD})

        # (c) Turn security on, authenticating as admin.
        admin_auth = ("admin", ADMIN_PASSWORD)
        _call("POST", "/rest/security", auth=admin_auth, json=True)

        # (d) Create the read-only reader account and grant read on the repo.
        # POST creates; a second POST on an existing user is 400, so the
        # authority grant goes via PUT (full replace incl. username).
        _call("POST", "/rest/security/users/reader", auth=admin_auth,
              json={"username": "reader", "password": READER_PASSWORD})
        _call("PUT", "/rest/security/users/reader", auth=admin_auth,
              json={"username": "reader",
                    "grantedAuthorities": [f"READ_REPO_{GRAPHDB_REPO}"]})

    except requests.RequestException as exc:
        print(f"ERROR: GraphDB security setup failed: {exc}", file=sys.stderr)
        return 1

    print(
        "GraphDB security enabled. Set for the app:\n"
        f"  GRAPHDB_USER=reader\n"
        f"  GRAPHDB_PASSWORD={READER_PASSWORD}\n"
        f"Use admin creds (admin / {ADMIN_PASSWORD}) for load.py ingest writes."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
