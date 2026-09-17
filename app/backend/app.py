"""Minimal FastAPI backend (M5).

Exposes only a health probe and the chat endpoint; the UI is a later milestone.
Business logic lives in the answerers selected via :func:`factory.get_answerer`.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import config
from app.auth.deps import get_current_user
from app.auth.routes import router as auth_router
from app.backend.factory import get_answerer
from app.backend.graphdb_proxy import router as graphdb_proxy_router
from app.backend.ingest import router as ingest_router
from app.backend.schemas import ChatRequest
from app.db import engine as db_engine
from app.db.models import Base, Chat, Message, User
from app.db.session import get_db

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

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # create_all is our schema mechanism (no Alembic). Failures are logged, not
    # raised, so the app still boots offline/stub without a reachable Postgres.
    try:
        Base.metadata.create_all(db_engine.get_engine())
    except Exception:
        logging.getLogger(__name__).warning(
            "schema create_all failed; continuing without a live database",
            exc_info=True,
        )
    yield


app = FastAPI(
    title="Sales Intelligence API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# Permissive CORS for local development only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth router is public (register/login/me).
app.include_router(auth_router)

# GraphDB visual proxy (authenticated inside the endpoint via get_current_user).
app.include_router(graphdb_proxy_router)

# Ingestion router is included before the static mount so /api/ingest wins over
# the catch-all UI mount. It is authenticated.
app.include_router(ingest_router, dependencies=[Depends(get_current_user)])


@app.get("/health")
def health() -> dict:
    body = {"status": "ok", "answerer": config.ANSWERER}
    try:
        with db_engine.get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        body["db"] = "ok"
    except Exception:
        body["db"] = "unavailable"
    return body


def _persist_chat(user_id: int, user_message: str, assistant_message: str) -> None:
    """Best-effort persist of one exchange; never raises into the caller."""
    try:
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(
            bind=db_engine.get_engine(), autocommit=False, autoflush=False
        )
        db = Session()
        try:
            chat = db.scalar(
                select(Chat).where(Chat.user_id == user_id).order_by(Chat.id).limit(1)
            )
            if chat is None:
                chat = Chat(user_id=user_id)
                db.add(chat)
                db.flush()
            db.add(Message(chat_id=chat.id, role="user", content=user_message))
            db.add(
                Message(chat_id=chat.id, role="assistant", content=assistant_message)
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        logging.getLogger(__name__).warning(
            "chat persistence failed; returning the answer anyway", exc_info=True
        )


@app.post("/api/chat")
def chat(
    request: ChatRequest, current_user: User = Depends(get_current_user)
) -> dict:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must be a non-empty string")

    try:
        response = get_answerer().answer(message, request.history)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _persist_chat(current_user.id, message, response.answer)

    return {
        "answer": response.answer,
        "sources": response.sources,
        "meta": response.meta,
    }


@app.get("/api/chats")
def list_chats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chats = db.scalars(
        select(Chat).where(Chat.user_id == current_user.id).order_by(Chat.id)
    ).all()

    result = []
    for chat in chats:
        messages = db.scalars(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.id)
        ).all()
        result.append(
            {
                "id": chat.id,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
            }
        )

    return {"chats": result}


@app.get("/api/transcripts/{transcript_id}")
def get_transcript_endpoint(
    transcript_id: str, current_user: User = Depends(get_current_user)
) -> dict:
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
