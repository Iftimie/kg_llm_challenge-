"""FastAPI auth dependencies: bearer-token parsing + current-user lookup."""
from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.db.models import User
from app.db.session import get_db

scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(scheme),
    sales_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated ``User`` from bearer token (first) or cookie.

    The bearer token takes priority; when absent, fall back to the ``sales_token``
    httpOnly cookie (used by plain ``<a>`` visual links, which cannot send an
    Authorization header). Either missing/invalid means ``401``.
    """
    if credentials is not None:
        token = credentials.credentials
    elif sales_token:
        token = sales_token
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user
