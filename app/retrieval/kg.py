"""SPARQL retrieval against the GraphDB repository (stdlib + requests)."""
import requests

from app import config
from app.mcp.guards import assert_readonly
from app.retrieval import graphdb_auth

_ACCEPT = "application/sparql-results+json"


def run_sparql(sparql, timeout=60, max_rows=100) -> dict:
    """Run a SPARQL query and return the parsed ``sparql-results+json`` payload.

    Bindings are truncated to ``max_rows``. Raises ``RuntimeError`` with a clean
    message when GraphDB is unreachable, returns a bad status, or sends non-JSON.
    The read-only guard runs first so no update query can reach GraphDB.
    """
    assert_readonly(sparql)
    url = f"{config.GRAPHDB_URL.rstrip('/')}/repositories/{config.GRAPHDB_REPO}"

    try:
        resp = requests.get(
            url,
            params={"query": sparql},
            headers={"Accept": _ACCEPT},
            timeout=timeout,
            auth=graphdb_auth.auth(),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"GraphDB unreachable at {url}: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"GraphDB returned HTTP {resp.status_code} for {url}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"GraphDB returned a non-JSON response from {url}") from exc

    bindings = payload.get("results", {}).get("bindings")
    if isinstance(bindings, list) and len(bindings) > max_rows:
        payload.setdefault("meta", {})["row_total"] = len(bindings)
        payload["results"]["bindings"] = bindings[:max_rows]

    return payload
