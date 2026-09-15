"""Minimal FastAPI backend (M5).

Exposes only a health probe and the chat endpoint; the UI is a later milestone.
Business logic lives in the answerers selected via :func:`factory.get_answerer`.
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import config
from app.backend.factory import get_answerer
from app.backend.schemas import ChatRequest

# Configure logging before defining routes so all module loggers inherit it.
config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
    force=True,
)
logging.getLogger(__name__).info("logging to %s level=%s", config.LOG_FILE, config.LOG_LEVEL)

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


@app.get("/api/transcripts/{transcript_id}")
def get_transcript_endpoint(transcript_id: str) -> dict:
    # Imported lazily so startup stays light and independent of CRM data.
    from app.retrieval.transcripts import get_transcript

    try:
        return get_transcript(transcript_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"unknown transcript {transcript_id}"
        ) from exc


# Mounted last so the explicit /health and /api/chat routes keep priority.
UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
