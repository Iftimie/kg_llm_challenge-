"""Authenticated streaming proxy for GraphDB visualizations (M4a).

The browser cannot reach GraphDB directly (compose publishes no host ports), so
the UI points its visual links at ``GET /api/graphdb/visual``. This router
validates the request, then forwards it to GraphDB's internal
``/graphs-visualizations`` endpoint and streams the response back unchanged.

GraphDB 10.6 returns 406 for the default ``Accept: */*`` sent by ``requests``,
so the upstream call must explicitly request ``Accept: text/html``.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import requests
from fastapi import APIRouter, Depends, HTTPException, Response

from app import config
from app.auth.deps import get_current_user
from app.db.models import User
from app.retrieval import graphdb_auth

router = APIRouter()

_ROLES = {"subject", "object", "predicate", "context"}


@router.get("/api/graphdb/visual")
def visual(
    uri: str,
    role: str = "subject",
    current_user: User = Depends(get_current_user),
) -> Response:
    """Forward a GraphDB visualization request, guarding against SSRF."""
    if role not in _ROLES:
        raise HTTPException(
            status_code=400,
            detail="role must be one of subject, object, predicate, context",
        )

    if any(ch.isspace() for ch in uri):
        raise HTTPException(status_code=400, detail="uri must not contain whitespace")

    parts = urlsplit(uri)
    if parts.scheme not in {"http", "https"} or not parts.netloc or "@" in parts.netloc:
        raise HTTPException(
            status_code=400, detail="uri must be an absolute http(s) IRI"
        )

    upstream = config.GRAPHDB_URL.rstrip("/") + "/graphs-visualizations"
    try:
        resp = requests.get(
            upstream,
            params={"uri": uri, "role": role},
            timeout=config.GRAPHDB_TIMEOUT_S,
            auth=graphdb_auth.auth(),
            headers={"Accept": "text/html"},
        )
    except requests.Timeout as exc:
        raise HTTPException(
            status_code=504, detail="GraphDB visualization request timed out"
        ) from exc
    except requests.ConnectionError as exc:
        raise HTTPException(status_code=502, detail="GraphDB unreachable") from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"GraphDB returned {resp.status_code}"
        )

    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "text/html"),
        status_code=200,
    )
