"""Auth routes: register, login and current-user lookup."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.schemas import LoginIn, MeOut, RegisterIn, TokenOut
from app.auth.security import create_token, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/auth")


@router.post("/register", status_code=201, response_model=MeOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> MeOut:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return MeOut(id=user.id, email=user.email)


@router.post("/login", response_model=TokenOut)
def login(
    payload: LoginIn, response: Response, db: Session = Depends(get_db)
) -> TokenOut:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")

    token = create_token(user.id, user.email)
    # httpOnly cookie enables cookie-fallback auth for plain <a> visual links.
    response.set_cookie(
        key="sales_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return TokenOut(access_token=token)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("sales_token", path="/")
    return {"status": "ok"}


@router.get("/me", response_model=MeOut)
def me(current_user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(id=current_user.id, email=current_user.email)
