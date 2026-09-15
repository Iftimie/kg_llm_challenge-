"""Minimal FastAPI backend (M5).

Exposes only a health probe and the chat endpoint; the UI is a later milestone.
Business logic lives in the answerers selected via :func:`factory.get_answerer`.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import config
from app.backend.factory import get_answerer
from app.backend.schemas import ChatRequest

app = FastAPI(
    title="Sales Intelligence API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Permissive CORS for local development only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "answerer": config.ANSWERER}


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must be a non-empty string")

    try:
        response = get_answerer().answer(message, request.history)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "answer": response.answer,
        "sources": response.sources,
        "meta": response.meta,
    }


# Mounted last so the explicit /health and /api/chat routes keep priority.
UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
